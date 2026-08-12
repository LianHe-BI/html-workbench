#!/usr/bin/env python3
"""Dependency-free local service for the HTML visual workbench."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


SERVICE_NAME = "html-workbench"
SERVICE_VERSION = "2.0.0"
DEFAULT_PORT = 4317
MAX_REQUEST_BYTES = 8 * 1024 * 1024
SCRIPT_PATTERN = re.compile(r"^<script\b[\s\S]*</script\s*>$", re.IGNORECASE)
GRAPESJS_VERSION = "0.23.4"
VENDOR_ASSETS = {
    "grapes.min.js": {
        "route": "/vendor/grapesjs/grapes.min.js",
        "archive": "package/dist/grapes.min.js",
        "sha256": "66155421db3a640add8eaf77391b6a744d36af80833cd91d44f8d3220fb76231",
        "content_type": "text/javascript; charset=utf-8",
    },
    "grapes.min.css": {
        "route": "/vendor/grapesjs/css/grapes.min.css",
        "archive": "package/dist/css/grapes.min.css",
        "sha256": "fb55e939b3349c280d68c0617dc87e56baa3eab55ea56a1855db9f5efcc7268d",
        "content_type": "text/css; charset=utf-8",
    },
}
VENDOR_ARCHIVES = [
    ("npmmirror", f"https://registry.npmmirror.com/grapesjs/-/grapesjs-{GRAPESJS_VERSION}.tgz"),
]
VENDOR_CDNS = [
    ("cdnjs", f"https://cdnjs.cloudflare.com/ajax/libs/grapesjs/{GRAPESJS_VERSION}"),
    ("jsdelivr", f"https://cdn.jsdelivr.net/npm/grapesjs@{GRAPESJS_VERSION}/dist"),
    ("unpkg", f"https://unpkg.com/grapesjs@{GRAPESJS_VERSION}/dist"),
]


class WorkbenchError(Exception):
    def __init__(self, code: str, message: str, status: int = 500, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.extra = extra


def default_vendor_cache() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "html-workbench" / "vendor" / "grapesjs" / GRAPESJS_VERSION


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def verify_vendor_content(name: str, content: bytes) -> bytes:
    expected = str(VENDOR_ASSETS[name]["sha256"])
    actual = sha256_bytes(content)
    if actual != expected:
        raise ValueError(f"{name} 校验失败（预期 {expected}，实际 {actual}）")
    return content


def download_bytes(url: str, limit: int = 5_000_000, timeout: float = 20.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": f"html-workbench/{SERVICE_VERSION}"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError(f"下载内容超过 {limit} 字节")
    return content


def vendor_from_archive(url: str) -> dict[str, bytes]:
    archive = download_bytes(url)
    files: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as package:
        members = {member.name: member for member in package.getmembers() if member.isfile()}
        for name, metadata in VENDOR_ASSETS.items():
            archive_name = str(metadata["archive"])
            member = members.get(archive_name)
            if member is None:
                raise ValueError(f"压缩包缺少 {archive_name}")
            source = package.extractfile(member)
            if source is None:
                raise ValueError(f"无法读取 {archive_name}")
            files[name] = verify_vendor_content(name, source.read())
    return files


def vendor_from_cdn(base_url: str) -> dict[str, bytes]:
    return {
        name: verify_vendor_content(
            name,
            download_bytes(f"{base_url}/{'css/' if name.endswith('.css') else ''}{name}"),
        )
        for name in VENDOR_ASSETS
    }


def write_vendor_cache(cache_dir: Path, files: dict[str, bytes]) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{name}.", dir=cache_dir)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, cache_dir / name)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)


def ensure_vendor_assets(cache_dir: Path) -> dict[str, Path]:
    paths = {name: cache_dir / name for name in VENDOR_ASSETS}
    try:
        for name, path in paths.items():
            verify_vendor_content(name, path.read_bytes())
        return paths
    except (OSError, ValueError):
        pass

    failures: list[str] = []
    sources = [
        *((name, url, vendor_from_archive) for name, url in VENDOR_ARCHIVES),
        *((name, url, vendor_from_cdn) for name, url in VENDOR_CDNS),
    ]
    for source_name, url, loader in sources:
        try:
            files = loader(url)
            write_vendor_cache(cache_dir, files)
            return paths
        except (OSError, ValueError, tarfile.TarError, urllib.error.URLError) as caught:
            failures.append(f"{source_name}: {caught}")
    raise WorkbenchError(
        "VENDOR_DOWNLOAD_FAILED",
        "首次启动需要下载约 1.2 MB 的 GrapesJS，但所有下载源均不可用。请检查网络后重试。",
        503,
        attempts=failures,
    )


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    start: int
    start_end: int
    parent: "HtmlNode | None" = None
    end_start: int | None = None
    end_end: int | None = None
    children: list["HtmlNode"] = field(default_factory=list)

    def is_inside(self, ancestor: "HtmlNode") -> bool:
        current = self.parent
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False


class SourceHtmlParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=False)
        self.source = source
        self.line_offsets: list[int] = [0]
        for match in re.finditer(r"\n", source):
            self.line_offsets.append(match.end())
        self.nodes: list[HtmlNode] = []
        self.stack: list[HtmlNode] = []

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.line_offsets[line - 1] + column

    @staticmethod
    def normalize_attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {name: value if value is not None else "" for name, value in attrs}

    def add_node(self, tag: str, attrs: list[tuple[str, str | None]], closed: bool) -> None:
        start = self.source_offset()
        raw = self.get_starttag_text() or ""
        parent = self.stack[-1] if self.stack else None
        node = HtmlNode(tag.lower(), self.normalize_attrs(attrs), start, start + len(raw), parent)
        if parent is not None:
            parent.children.append(node)
        self.nodes.append(node)
        if closed:
            node.end_start = node.start_end
            node.end_end = node.start_end
        else:
            self.stack.append(node)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.add_node(tag, attrs, tag.lower() in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"})

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.add_node(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        target = tag.lower()
        index = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i].tag == target), None)
        if index is None:
            return
        start = self.source_offset()
        match = re.match(r"</\s*[^>]+>", self.source[start:], re.IGNORECASE)
        end = start + (len(match.group(0)) if match else len(tag) + 3)
        node = self.stack[index]
        node.end_start = start
        node.end_end = end
        del self.stack[index:]


def parse_source(source: str) -> dict[str, Any]:
    parser = SourceHtmlParser(source)
    try:
        parser.feed(source)
        parser.close()
    except Exception as caught:
        raise WorkbenchError("INVALID_DOCUMENT", f"HTML 解析失败：{caught}", 400) from caught

    def first(tag: str) -> HtmlNode | None:
        return next((node for node in parser.nodes if node.tag == tag), None)

    html_node = first("html")
    head_node = first("head")
    body_node = first("body")
    if not html_node or not head_node or not body_node or body_node.end_start is None or head_node.end_start is None:
        raise WorkbenchError("INVALID_DOCUMENT", "目标必须是包含 html、head、body 的完整 HTML 文档。", 400)

    head_children = [node for node in parser.nodes if node.parent is head_node]
    override = next(
        (node for node in head_children if node.tag == "style" and "data-grapesjs-overrides" in node.attrs),
        None,
    )

    def inner(node: HtmlNode) -> str:
        if node.end_start is None:
            return ""
        return source[node.start_end : node.end_start]

    source_css = "\n".join(inner(node) for node in head_children if node.tag == "style" and node is not override)
    links = [
        node.attrs.get("href", "")
        for node in head_children
        if node.tag == "link" and node.attrs.get("rel", "").lower() == "stylesheet" and node.attrs.get("href")
    ]
    head_scripts = [
        {"attributes": node.attrs, "content": inner(node)}
        for node in head_children
        if node.tag == "script" and node.end_start is not None
    ]

    raw_body = source[body_node.start_end : body_node.end_start]
    body_script_nodes = [
        node
        for node in parser.nodes
        if node.tag == "script" and node.end_end is not None and node.is_inside(body_node)
    ]
    body_scripts = [source[node.start : node.end_end] for node in body_script_nodes]
    clean_body = raw_body
    for node in sorted(body_script_nodes, key=lambda item: item.start, reverse=True):
        relative_start = node.start - body_node.start_end
        relative_end = node.end_end - body_node.start_end
        clean_body = clean_body[:relative_start] + clean_body[relative_end:]

    return {
        "bodyHtml": clean_body,
        "bodyScripts": body_scripts,
        "sourceCss": source_css,
        "overrideCss": inner(override) if override else "",
        "links": links,
        "headScripts": head_scripts,
        "htmlAttributes": html_node.attrs,
        "bodyAttributes": body_node.attrs,
        "locations": {
            "bodyStart": body_node.start_end,
            "bodyEnd": body_node.end_start,
            "headEnd": head_node.end_start,
            "overrideStart": override.start if override else None,
            "overrideEnd": override.end_end if override else None,
        },
    }


def revision_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def inside_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_html_file(raw_file: str, editor_root: Path) -> Path:
    if not raw_file.strip():
        raise WorkbenchError("FILE_REQUIRED", "请通过 file 参数指定 HTML 文件。", 400)
    requested = Path(raw_file).expanduser()
    try:
        target = requested.resolve(strict=True)
    except FileNotFoundError as caught:
        raise WorkbenchError("FILE_NOT_FOUND", f"找不到文件：{requested.resolve()}", 404) from caught
    if target.suffix.lower() != ".html":
        raise WorkbenchError("INVALID_DOCUMENT", "只支持本地 .html 文件。", 400)
    if not inside_root(target, editor_root):
        raise WorkbenchError("OUTSIDE_EDITOR_ROOT", f"文件不在允许目录中：{target}", 403)
    return target


def encode_asset_token(target: Path) -> str:
    return base64.urlsafe_b64encode(str(target).encode("utf-8")).decode("ascii").rstrip("=")


def decode_asset_token(token: str) -> str:
    padding = "=" * (-len(token) % 4)
    try:
        return base64.urlsafe_b64decode(token + padding).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as caught:
        raise WorkbenchError("INVALID_ASSET", "资源地址无效。", 400) from caught


def read_document(target: Path) -> dict[str, Any]:
    try:
        source = target.read_text(encoding="utf-8")
    except UnicodeDecodeError as caught:
        raise WorkbenchError("INVALID_DOCUMENT", "HTML 文件必须使用 UTF-8 编码。", 400) from caught
    parsed = parse_source(source)
    stat = target.stat()
    return {
        **parsed,
        "html": source,
        "revision": revision_of(source),
        "mtimeMs": stat.st_mtime * 1000,
        "filePath": str(target),
        "fileName": target.name,
        "assetBase": f"/assets/{encode_asset_token(target)}/",
    }


def save_document(target: Path, body: dict[str, Any]) -> dict[str, Any]:
    base_revision = body.get("baseRevision")
    body_html = body.get("bodyHtml")
    css = body.get("css")
    if not isinstance(base_revision, str) or not isinstance(body_html, str) or not isinstance(css, str):
        raise WorkbenchError("INVALID_SAVE", "保存请求必须包含 baseRevision、bodyHtml 和 css。", 400)
    if len(body_html) > 6_000_000 or len(css) > 1_000_000:
        raise WorkbenchError("INVALID_SAVE", "保存内容超过大小限制。", 400)
    if re.search(r"<(?:html|head|body)\b", body_html, re.IGNORECASE) or re.search(r"<script\b", body_html, re.IGNORECASE):
        raise WorkbenchError("INVALID_SAVE", "bodyHtml 不允许包含 html、head、body 或 script。", 400)

    current = read_document(target)
    if current["revision"] != base_revision:
        raise WorkbenchError("REVISION_CONFLICT", "磁盘文件已被外部修改，未覆盖最新版。", 409, document=current)

    source = current["html"]
    locations = current["locations"]
    override = f"<style data-grapesjs-overrides>\n{css}\n</style>\n"
    if locations["overrideStart"] is not None:
        source = source[: locations["overrideStart"]] + override + source[locations["overrideEnd"] :]
    else:
        source = source[: locations["headEnd"]] + override + source[locations["headEnd"] :]

    refreshed = parse_source(source)
    scripts = body.get("bodyScripts")
    if isinstance(scripts, list) and all(isinstance(item, str) and SCRIPT_PATTERN.match(item.strip()) for item in scripts):
        preserved_scripts = "\n".join(scripts)
    else:
        preserved_scripts = "\n".join(current["bodyScripts"])
    next_body = f"{body_html}\n{preserved_scripts}" if preserved_scripts else body_html
    body_start = refreshed["locations"]["bodyStart"]
    body_end = refreshed["locations"]["bodyEnd"]
    source = source[:body_start] + "\n" + next_body + "\n" + source[body_end:]

    latest = read_document(target)
    if latest["revision"] != base_revision:
        raise WorkbenchError("REVISION_CONFLICT", "保存期间文件发生外部修改，未覆盖最新版。", 409, document=latest)

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.workbench-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(source)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary_name, target.stat().st_mode)
        os.replace(temporary_name, target)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return read_document(target)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], asset_file: Path, editor_root: Path, vendor_files: dict[str, Path]) -> None:
        self.asset_file = asset_file.resolve(strict=True)
        self.editor_root = editor_root.resolve(strict=True)
        self.vendor_files = {name: path.resolve(strict=True) for name, path in vendor_files.items()}
        self.vendor_routes = {str(metadata["route"]): name for name, metadata in VENDOR_ASSETS.items()}
        super().__init__(address, WorkbenchHandler)


class WorkbenchHandler(BaseHTTPRequestHandler):
    server: WorkbenchServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args: Any) -> None:
        sys.stderr.write(f"{self.log_date_time_string()} {format_string % args}\n")

    def send_bytes(self, status: int, content: bytes, content_type: str, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        if cache == "no-store":
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        else:
            self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_bytes(status, content, "application/json; charset=utf-8")

    def send_error_payload(self, caught: Exception) -> None:
        if isinstance(caught, WorkbenchError):
            self.send_json(caught.status, {"error": caught.code, "message": str(caught), **caught.extra})
        else:
            self.send_json(500, {"error": "SERVER_ERROR", "message": str(caught)})

    def query_file(self, query: dict[str, list[str]]) -> Path:
        return resolve_html_file(query.get("file", [""])[0], self.server.editor_root)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/health":
                self.send_json(200, {
                    "ok": True,
                    "service": SERVICE_NAME,
                    "version": SERVICE_VERSION,
                    "port": self.server.server_port,
                    "editorRoot": str(self.server.editor_root),
                    "capabilities": ["grapesjs-canvas", "autosave", "file-query", "file-watch", "stdlib-python"],
                })
                return
            if parsed.path == "/api/document":
                self.send_json(200, read_document(self.query_file(query)))
                return
            if parsed.path == "/api/events":
                self.stream_events(self.query_file(query))
                return
            if parsed.path.startswith("/assets/"):
                self.send_asset(parsed.path)
                return
            if parsed.path in self.server.vendor_routes:
                name = self.server.vendor_routes[parsed.path]
                metadata = VENDOR_ASSETS[name]
                self.send_bytes(200, self.server.vendor_files[name].read_bytes(), str(metadata["content_type"]), "public, max-age=31536000, immutable")
                return
            self.send_bytes(200, self.server.asset_file.read_bytes(), "text/html; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as caught:
            self.send_error_payload(caught)

    def do_PUT(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path != "/api/document":
            self.send_json(404, {"error": "NOT_FOUND", "message": "接口不存在。"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise WorkbenchError("INVALID_SAVE", "保存请求大小无效。", 400)
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            query = urllib.parse.parse_qs(parsed.query)
            self.send_json(200, save_document(self.query_file(query), body))
        except json.JSONDecodeError as caught:
            self.send_error_payload(WorkbenchError("INVALID_SAVE", f"保存请求不是有效 JSON：{caught}", 400))
        except Exception as caught:
            self.send_error_payload(caught)

    def send_asset(self, route: str) -> None:
        parts = route.split("/", 3)
        if len(parts) < 4:
            raise WorkbenchError("INVALID_ASSET", "资源地址无效。", 400)
        token = parts[2]
        source_file = resolve_html_file(decode_asset_token(token), self.server.editor_root)
        relative = urllib.parse.unquote(parts[3])
        resource = (source_file.parent / relative).resolve(strict=True)
        if not inside_root(resource, self.server.editor_root):
            raise WorkbenchError("OUTSIDE_EDITOR_ROOT", "资源超出允许目录。", 403)
        content_type = mimetypes.guess_type(resource.name)[0] or "application/octet-stream"
        self.send_bytes(200, resource.read_bytes(), content_type, "private, max-age=60")

    def stream_events(self, target: Path) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last_revision = ""
        while True:
            try:
                document = read_document(target)
                if document["revision"] != last_revision:
                    last_revision = document["revision"]
                    payload = json.dumps({"revision": last_revision, "mtimeMs": document["mtimeMs"]}, separators=(",", ":"))
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except FileNotFoundError:
                self.wfile.write(b'event: error\ndata: {"error":"FILE_NOT_FOUND"}\n\n')
                self.wfile.flush()
            time.sleep(0.5)


def default_asset_file(script_file: Path) -> Path:
    packaged = script_file.parent.parent / "assets" / "workbench.html"
    if packaged.is_file():
        return packaged
    raise WorkbenchError("ASSET_NOT_FOUND", f"找不到前端资源：{packaged}", 500)


def health(port: int, timeout: float = 0.5) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload if payload.get("service") == SERVICE_NAME else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def start_detached(script_file: Path, port: int, editor_root: Path, asset_file: Path | None, vendor_cache: Path) -> tuple[int, Path]:
    log_file = Path(tempfile.gettempdir()) / f"html-workbench-{port}.log"
    command = [sys.executable, str(script_file), "serve", "--port", str(port), "--editor-root", str(editor_root), "--vendor-cache", str(vendor_cache)]
    if asset_file is not None:
        command.extend(["--asset", str(asset_file)])
    flags = 0
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "start_new_session": os.name != "nt"}
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        kwargs["creationflags"] = flags
        kwargs.pop("start_new_session", None)
    with log_file.open("ab") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, close_fds=True, **kwargs)
    return process.pid, log_file


def command_serve(args: argparse.Namespace, script_file: Path) -> int:
    asset_file = Path(args.asset).expanduser().resolve(strict=True) if args.asset else default_asset_file(script_file)
    editor_root = Path(args.editor_root).expanduser().resolve(strict=True)
    vendor_files = ensure_vendor_assets(Path(args.vendor_cache).expanduser())
    server = WorkbenchServer(("127.0.0.1", args.port), asset_file, editor_root, vendor_files)
    print(json.dumps({"ok": True, "url": f"http://127.0.0.1:{args.port}", "editorRoot": str(editor_root)}, ensure_ascii=False), flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def command_open(args: argparse.Namespace, script_file: Path) -> int:
    target = Path(args.file).expanduser().resolve(strict=True)
    editor_root = Path(args.editor_root).expanduser().resolve(strict=True)
    resolve_html_file(str(target), editor_root)
    existing = health(args.port)
    reused = existing is not None
    pid: int | None = None
    log_file: Path | None = None
    if not reused:
        asset_file = Path(args.asset).expanduser().resolve(strict=True) if args.asset else None
        pid, log_file = start_detached(script_file, args.port, editor_root, asset_file, Path(args.vendor_cache).expanduser())
        deadline = time.monotonic() + args.wait
        while time.monotonic() < deadline:
            if health(args.port):
                break
            time.sleep(0.1)
        else:
            raise WorkbenchError("SERVER_UNAVAILABLE", f"服务启动失败，请查看日志：{log_file}", 500)
    query = urllib.parse.urlencode({"file": str(target)})
    print(json.dumps({
        "ok": True,
        "url": f"http://127.0.0.1:{args.port}/?{query}",
        "reused": reused,
        **({"pid": pid} if pid else {}),
    }, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start and use the local HTML visual workbench.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve = subparsers.add_parser("serve", help="run the service in the foreground")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--editor-root", default=str(Path.home()))
    serve.add_argument("--asset", help="override the bundled workbench.html path")
    serve.add_argument("--vendor-cache", default=str(default_vendor_cache()), help="directory for verified GrapesJS files")

    open_command = subparsers.add_parser("open", help="start or reuse the service and print an editor URL")
    open_command.add_argument("file")
    open_command.add_argument("--port", type=int, default=DEFAULT_PORT)
    open_command.add_argument("--editor-root", default=str(Path.home()))
    open_command.add_argument("--asset", help="override the bundled workbench.html path")
    open_command.add_argument("--vendor-cache", default=str(default_vendor_cache()), help="directory for verified GrapesJS files")
    open_command.add_argument("--wait", type=float, default=8.0)

    health_command = subparsers.add_parser("health", help="check the local service")
    health_command.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main() -> int:
    if sys.version_info < (3, 9):
        print(json.dumps({"ok": False, "error": "PYTHON_TOO_OLD", "message": "需要 Python 3.9 或更高版本。"}, ensure_ascii=False), file=sys.stderr)
        return 2
    args = build_parser().parse_args()
    script_file = Path(__file__).resolve()
    try:
        if args.command == "serve":
            return command_serve(args, script_file)
        if args.command == "open":
            return command_open(args, script_file)
        payload = health(args.port)
        print(json.dumps(payload or {"ok": False, "error": "SERVER_UNAVAILABLE"}, ensure_ascii=False))
        return 0 if payload else 1
    except WorkbenchError as caught:
        print(json.dumps({"ok": False, "error": caught.code, "message": str(caught)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except FileNotFoundError as caught:
        print(json.dumps({"ok": False, "error": "FILE_NOT_FOUND", "message": str(caught)}, ensure_ascii=False), file=sys.stderr)
        return 1
    except OSError as caught:
        code = "PORT_IN_USE" if getattr(caught, "errno", None) in {48, 98, 10048} else "SERVER_UNAVAILABLE"
        print(json.dumps({"ok": False, "error": code, "message": str(caught)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
