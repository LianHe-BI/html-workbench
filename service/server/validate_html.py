#!/usr/bin/env python3
"""Validate HTML for resilient editing in HTML Workbench using only the stdlib."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Issue:
    severity: str
    rule: str
    line: int
    message: str


class WorkbenchHtmlInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.document_tags: set[str] = set()
        self.html_ids: dict[str, list[int]] = {}
        self.workbench_ids: dict[str, list[int]] = {}
        self.targets: list[tuple[str, int]] = []
        self.unsafe_urls: list[tuple[str, str, int]] = []
        self.resource_urls: list[tuple[str, str, str, int]] = []
        self.inline_blocks: dict[str, list[tuple[int, str]]] = {"script": [], "style": []}
        self.external_scripts: list[tuple[int, str]] = []
        self.inline_event_handlers: list[tuple[str, int]] = []
        self._active_block: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        line, _ = self.getpos()
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag in {"html", "head", "body"}:
            self.document_tags.add(tag)
        if attributes.get("id"):
            self.html_ids.setdefault(attributes["id"], []).append(line)
        if "data-wb-id" in attributes:
            self.workbench_ids.setdefault(attributes["data-wb-id"], []).append(line)
        if "data-target" in attributes:
            self.targets.append((attributes["data-target"], line))
        self.inline_event_handlers.extend(
            (name, line) for name in attributes if name.startswith("on")
        )
        for name in ("href", "src", "action", "formaction"):
            value = attributes.get(name, "").strip()
            if value.lower().startswith("javascript:"):
                self.unsafe_urls.append((name, value, line))
        if tag == "link" and "stylesheet" in attributes.get("rel", "").lower().split():
            self.add_resource_url(tag, "href", attributes.get("href", ""), line)
        elif tag in {"audio", "embed", "iframe", "img", "script", "source", "track", "video"}:
            self.add_resource_url(tag, "src", attributes.get("src", ""), line)
            self.add_resource_url(tag, "srcset", attributes.get("srcset", ""), line)
        elif tag == "object":
            self.add_resource_url(tag, "data", attributes.get("data", ""), line)
        if tag == "script" and attributes.get("src"):
            self.external_scripts.append((line, attributes["src"]))
        if tag in self.inline_blocks and not (tag == "script" and attributes.get("src")):
            self._active_block = {"tag": tag, "line": line, "parts": []}

    def add_resource_url(self, tag: str, attribute: str, value: str, line: int) -> None:
        if value.strip():
            self.resource_urls.append((tag, attribute, value.strip(), line))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        normalized = tag.lower()
        if self._active_block is not None and self._active_block["tag"] == normalized:
            line = int(self._active_block["line"])
            self.inline_blocks[normalized].append((line, ""))
            self._active_block = None

    def handle_data(self, data: str) -> None:
        if self._active_block is not None:
            parts = self._active_block["parts"]
            assert isinstance(parts, list)
            parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._active_block is None or self._active_block["tag"] != tag:
            return
        line = int(self._active_block["line"])
        parts = self._active_block["parts"]
        assert isinstance(parts, list)
        self.inline_blocks[tag].append((line, "".join(parts)))
        self._active_block = None


JS_RULES = (
    (
        "position-dependent-js-selector",
        re.compile(r":nth-(?:child|of-type)\s*\(", re.IGNORECASE),
        "JS 使用了位置选择器；元素拖动或插入后可能指向其他节点。",
    ),
    (
        "structural-dom-traversal",
        re.compile(r"\.(?:parentElement|nextElementSibling|previousElementSibling)\b|\.children\s*\["),
        "JS 依赖父子或兄弟层级；建议通过 data-target 与稳定标识定位。",
    ),
    (
        "indexed-node-lookup",
        re.compile(r"(?:querySelectorAll|getElementsBy(?:ClassName|TagName|Name))\s*\([^;\n]*?\)\s*\[\s*\d+\s*\]"),
        "JS 通过固定下标选择节点；元素重新排序后可能失效。",
    ),
    (
        "broad-dom-rewrite",
        re.compile(r"\.(?:innerHTML|outerHTML)\s*=|\bdocument\.write\s*\("),
        "JS 会重写 DOM；可能覆盖可视化编辑产生的内容。",
    ),
    (
        "per-node-event-binding",
        re.compile(r"querySelectorAll\s*\([^)]*\)\s*\.forEach\s*\([\s\S]{0,240}?addEventListener\s*\(", re.IGNORECASE),
        "JS 为当前节点逐个绑定事件；节点重建后监听可能丢失，建议使用事件委托。",
    ),
)

CSS_RULES = (
    (
        "position-dependent-css-selector",
        re.compile(r":nth-(?:child|of-type)\s*\(", re.IGNORECASE),
        "CSS 使用了位置选择器；元素拖动后视觉规则可能应用到其他节点。",
    ),
)
CSS_URL_PATTERN = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
CSS_IMPORT_PATTERN = re.compile(r"@import\s+(?:url\(\s*)?(['\"]?)([^'\"\s;)]+)\1", re.IGNORECASE)


def issue_for_match(severity: str, rule: str, message: str, base_line: int, source: str, offset: int) -> Issue:
    return Issue(severity, rule, base_line + source[:offset].count("\n"), message)


def scan_blocks(blocks: Iterable[tuple[int, str]], rules: tuple[tuple[str, re.Pattern[str], str], ...]) -> list[Issue]:
    issues: list[Issue] = []
    for base_line, source in blocks:
        for rule, pattern, message in rules:
            for match in pattern.finditer(source):
                issues.append(issue_for_match("warning", rule, message, base_line, source, match.start()))
    return issues


def is_self_contained_url(value: str) -> bool:
    normalized = value.strip().lower()
    return not normalized or normalized.startswith(("data:", "#", "about:blank"))


def self_contained_issues(inspector: WorkbenchHtmlInspector) -> list[Issue]:
    issues: list[Issue] = []
    for tag, attribute, value, line in inspector.resource_urls:
        if not is_self_contained_url(value):
            issues.append(Issue("error", "non-self-contained-resource", line, f"<{tag}> 的 {attribute} 引用了外部资源：{value}"))
    for base_line, source in inspector.inline_blocks["style"]:
        import_spans: list[tuple[int, int]] = []
        for match in CSS_IMPORT_PATTERN.finditer(source):
            import_spans.append(match.span())
            value = match.group(2)
            if not is_self_contained_url(value):
                issues.append(issue_for_match("error", "non-self-contained-resource", f"CSS @import 引用了外部资源：{value}", base_line, source, match.start()))
        for match in CSS_URL_PATTERN.finditer(source):
            if any(start <= match.start() < end for start, end in import_spans):
                continue
            value = match.group(2).strip()
            if not is_self_contained_url(value):
                issues.append(issue_for_match("error", "non-self-contained-resource", f"CSS url() 引用了外部资源：{value}", base_line, source, match.start()))
    return issues


def validate_source(source: str, file_name: str = "<memory>", require_self_contained: bool = False) -> dict[str, object]:
    inspector = WorkbenchHtmlInspector()
    parse_error: Exception | None = None
    try:
        inspector.feed(source)
        inspector.close()
    except Exception as caught:  # HTMLParser is permissive, but keep the result deterministic.
        parse_error = caught

    issues: list[Issue] = []
    if parse_error:
        issues.append(Issue("error", "html-parse-failed", 1, f"HTML 解析失败：{parse_error}"))
    missing = sorted({"html", "head", "body"} - inspector.document_tags)
    if missing:
        issues.append(Issue("error", "incomplete-document", 1, f"缺少完整文档标签：{', '.join(missing)}。"))

    for value, lines in inspector.workbench_ids.items():
        if not value.strip():
            issues.append(Issue("error", "empty-workbench-id", lines[0], "data-wb-id 不能为空。"))
        elif len(lines) > 1:
            issues.append(Issue("error", "duplicate-workbench-id", lines[1], f"data-wb-id '{value}' 在文档中不唯一。"))

    for value, lines in inspector.html_ids.items():
        if len(lines) > 1:
            issues.append(Issue("error", "duplicate-html-id", lines[1], f"id '{value}' 在文档中不唯一，交互目标会产生歧义。"))

    known_targets = set(inspector.html_ids) | set(inspector.workbench_ids)
    for target, line in inspector.targets:
        raw_target = target.strip()
        normalized = raw_target.removeprefix("#")
        if not re.fullmatch(r"[A-Za-z_][\w:.-]*", normalized):
            issues.append(Issue("warning", "non-stable-interaction-target", line, f"data-target '{target}' 不是稳定 ID；建议改用 id 或 data-wb-id。"))
        elif normalized not in known_targets:
            issues.append(Issue("error", "missing-interaction-target", line, f"data-target '{target}' 找不到对应的 id 或 data-wb-id。"))

    for attribute, value, line in inspector.unsafe_urls:
        issues.append(Issue("error", "dangerous-url", line, f"{attribute} 使用了不允许的 javascript: URL：{value}"))

    for attribute, line in inspector.inline_event_handlers:
        issues.append(Issue(
            "warning",
            "inline-event-handler",
            line,
            f"{attribute} 是内联事件属性；Workbench 会保留它，但建议改用 document 事件委托以适应可视化重排。",
        ))

    issues.extend(scan_blocks(inspector.inline_blocks["script"], JS_RULES))
    issues.extend(scan_blocks(inspector.inline_blocks["style"], CSS_RULES))
    if require_self_contained:
        issues.extend(self_contained_issues(inspector))
    for line, url in inspector.external_scripts:
        issues.append(Issue("info", "external-script-not-inspected", line, f"外部脚本未做静态检查：{url}"))

    severity_order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda item: (severity_order[item.severity], item.line, item.rule))
    grouped = {
        severity: [asdict(item) for item in issues if item.severity == severity]
        for severity in ("error", "warning", "info")
    }
    return {
        "ok": not grouped["error"],
        "file": file_name,
        "summary": {name: len(grouped[name]) for name in grouped},
        "errors": grouped["error"],
        "warnings": grouped["warning"],
        "info": grouped["info"],
    }


def validate_file(path: Path, require_self_contained: bool = False) -> dict[str, object]:
    target = path.expanduser().resolve()
    try:
        source = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as caught:
        issue = Issue("error", "file-unreadable", 1, f"无法读取 UTF-8 HTML：{caught}")
        return {
            "ok": False,
            "file": str(target),
            "summary": {"error": 1, "warning": 0, "info": 0},
            "errors": [asdict(issue)],
            "warnings": [],
            "info": [],
        }
    return validate_source(source, str(target), require_self_contained)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an HTML page for resilient HTML Workbench editing.")
    parser.add_argument("html_file", type=Path, help="Path to a complete UTF-8 HTML document")
    parser.add_argument("--require-self-contained", action="store_true", help="Reject referenced styles, scripts, media, and CSS resources")
    args = parser.parse_args(argv)
    result = validate_file(args.html_file, args.require_self_contained)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
