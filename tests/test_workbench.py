import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from unittest import mock
from html.parser import HTMLParser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "service" / "server" / "workbench.py"
SPEC = importlib.util.spec_from_file_location("workbench", MODULE_PATH)
workbench = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = workbench
SPEC.loader.exec_module(workbench)


SAMPLE_HTML = """<!doctype html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8">
  <link rel="stylesheet" href="styles/site.css">
  <style>.card { color: red; }</style>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="page">
  <main><h1>Hello</h1><img src="images/demo.png"></main>
  <script>window.ready = true</script>
</body>
</html>
"""


class BundleInspector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []
        self.links = []
        self.bundles = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script":
            self.scripts.append(attributes)
        if tag == "link":
            self.links.append(attributes)
        if attributes.get("data-bundle"):
            self.bundles.append((tag, attributes["data-bundle"]))


class BundleTests(unittest.TestCase):
    def test_frontend_keeps_only_vendor_assets_external(self):
        bundle = PROJECT_ROOT / "skill" / "html-workbench" / "assets" / "workbench.html"
        inspector = BundleInspector()
        inspector.feed(bundle.read_text(encoding="utf-8"))
        self.assertTrue(inspector.scripts)
        self.assertEqual(
            [script.get("src") for script in inspector.scripts if script.get("src")],
            ["/vendor/grapesjs/grapes.min.js"],
        )
        self.assertEqual(
            [link.get("href") for link in inspector.links if link.get("rel") == "stylesheet"],
            ["/vendor/grapesjs/css/grapes.min.css"],
        )
        self.assertEqual(sorted(inspector.bundles), [
            ("script", "workbench"),
            ("style", "workbench"),
        ])
        self.assertLess(bundle.stat().st_size, 100_000)

    def test_frontend_exposes_edit_and_preview_modes(self):
        bundle = PROJECT_ROOT / "skill" / "html-workbench" / "assets" / "workbench.html"
        source = bundle.read_text(encoding="utf-8")
        self.assertIn('data-mode="edit"', source)
        self.assertIn('data-mode="preview"', source)
        self.assertIn('id="preview-frame"', source)
        self.assertIn("previewFrame.srcdoc = buildPreviewDocument()", source)
        self.assertIn("workbenchMode !== 'edit'", source)


class ParserTests(unittest.TestCase):
    def test_fixture_contains_realistic_editable_sections(self):
        fixture = (PROJECT_ROOT / "tests" / "fixtures" / "sample.html").read_text(encoding="utf-8")
        document = workbench.parse_source(fixture)
        self.assertIn("class=\"hero", document["bodyHtml"])
        self.assertIn("class=\"bento", document["bodyHtml"])
        self.assertIn("class=\"workflow", document["bodyHtml"])
        self.assertIn("assets/workbench-studio.webp", document["bodyHtml"])
        self.assertGreater(len(document["bodyHtml"]), 3_000)

    def test_extracts_document_context(self):
        document = workbench.parse_source(SAMPLE_HTML)
        self.assertEqual(document["htmlAttributes"]["lang"], "zh-CN")
        self.assertEqual(document["bodyAttributes"]["class"], "page")
        self.assertEqual(document["links"], ["styles/site.css"])
        self.assertIn(".card", document["sourceCss"])
        self.assertEqual(document["headScripts"][0]["attributes"]["src"], "https://cdn.tailwindcss.com")
        self.assertNotIn("window.ready", document["bodyHtml"])
        self.assertIn("window.ready", document["bodyScripts"][0])

    def test_requires_complete_document(self):
        with self.assertRaises(workbench.WorkbenchError) as context:
            workbench.parse_source("<div>fragment</div>")
        self.assertEqual(context.exception.code, "INVALID_DOCUMENT")


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.page = self.root / "page.html"
        self.page.write_text(SAMPLE_HTML, encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_saves_body_and_override_css_atomically(self):
        current = workbench.read_document(self.page)
        updated = workbench.save_document(self.page, {
            "baseRevision": current["revision"],
            "bodyHtml": "<main><h1>Updated</h1></main>",
            "css": "h1 { color: blue; }",
            "bodyScripts": current["bodyScripts"],
        })
        source = self.page.read_text(encoding="utf-8")
        self.assertIn("<h1>Updated</h1>", source)
        self.assertIn("data-grapesjs-overrides", source)
        self.assertIn("h1 { color: blue; }", source)
        self.assertIn("window.ready = true", source)
        self.assertNotEqual(current["revision"], updated["revision"])

    def test_preserves_inline_event_attributes_stripped_by_grapesjs(self):
        source = """<!doctype html>
<html><head><title>Events</title></head><body>
  <button id="switcher" onclick="switchMode('daemon')">Daemon</button>
  <section data-mode="daemon"><p>Content</p></section>
  <script>function switchMode() {}</script>
</body></html>"""
        self.page.write_text(source, encoding="utf-8")
        current = workbench.read_document(self.page)
        # Simulate GrapesJS serialization: component markup retains the element
        # but silently drops its inline onclick attribute.
        workbench.save_document(self.page, {
            "baseRevision": current["revision"],
            "bodyHtml": """
  <button id=\"switcher\">Daemon</button>
  <section data-mode=\"daemon\"><p>Edited content</p></section>
""",
            "css": "",
            "bodyScripts": current["bodyScripts"],
        })
        saved = self.page.read_text(encoding="utf-8")
        self.assertIn('onclick="switchMode(&#x27;daemon&#x27;)"', saved)
        self.assertIn("Edited content", saved)

    def test_does_not_restore_handler_when_source_element_was_deleted(self):
        source = """<!doctype html>
<html><head><title>Events</title></head><body>
  <button id="removed" onclick="run()">Remove me</button>
</body></html>"""
        self.page.write_text(source, encoding="utf-8")
        current = workbench.read_document(self.page)
        workbench.save_document(self.page, {
            "baseRevision": current["revision"],
            "bodyHtml": "<main>Remaining content</main>",
            "css": "",
        })
        saved = self.page.read_text(encoding="utf-8")
        self.assertNotIn("onclick=", saved)

    def test_rejects_stale_revision(self):
        current = workbench.read_document(self.page)
        self.page.write_text(SAMPLE_HTML.replace("Hello", "External"), encoding="utf-8")
        with self.assertRaises(workbench.WorkbenchError) as context:
            workbench.save_document(self.page, {
                "baseRevision": current["revision"],
                "bodyHtml": "<main>Browser</main>",
                "css": "",
            })
        self.assertEqual(context.exception.code, "REVISION_CONFLICT")
        self.assertIn("External", context.exception.extra["document"]["html"])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.page = self.root / "page.html"
        self.page.write_text(SAMPLE_HTML, encoding="utf-8")
        self.asset = self.root / "workbench.html"
        self.asset.write_text("<!doctype html><title>Workbench</title>", encoding="utf-8")
        self.vendor = {}
        for name in workbench.VENDOR_ASSETS:
            path = self.root / name
            path.write_bytes(f"test-{name}".encode())
            self.vendor[name] = path
        self.server = workbench.WorkbenchServer(("127.0.0.1", 0), self.asset, self.root, self.vendor)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def read_json(self, route):
        with urllib.request.urlopen(self.base + route, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_and_document_endpoints(self):
        status, health = self.read_json("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["service"], workbench.SERVICE_NAME)
        query = urllib.parse.urlencode({"file": str(self.page)})
        status, document = self.read_json(f"/api/document?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(document["fileName"], "page.html")

    def test_serves_file_outside_editor_root(self):
        outside = Path(self.temp.name).parent / "outside-workbench.html"
        outside.write_text(SAMPLE_HTML, encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        query = urllib.parse.urlencode({"file": str(outside)})
        status, document = self.read_json(f"/api/document?{query}")
        self.assertEqual(status, 200)
        self.assertEqual(document["fileName"], "outside-workbench.html")

    def test_serves_vendor_assets_locally(self):
        route = workbench.VENDOR_ASSETS["grapes.min.js"]["route"]
        with urllib.request.urlopen(self.base + route, timeout=2) as response:
            self.assertEqual(response.read(), b"test-grapes.min.js")
            self.assertIn("immutable", response.headers["Cache-Control"])


class OpenCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.page = self.root / "page.html"
        self.page.write_text(SAMPLE_HTML, encoding="utf-8")
        self.args = SimpleNamespace(
            file=str(self.page),
            editor_root=str(self.root),
            port=4317,
            asset=None,
            vendor_cache=str(self.root / "vendor"),
            log_dir=str(self.root / "logs"),
            wait=0.2,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_open_reuses_healthy_service_without_starting_again(self):
        output = io.StringIO()
        with mock.patch.object(workbench, "health", return_value={"service": workbench.SERVICE_NAME}), \
             mock.patch.object(workbench, "start_detached") as start, \
             contextlib.redirect_stdout(output):
            self.assertEqual(workbench.command_open(self.args, MODULE_PATH), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["reused"])
        self.assertNotIn("pid", payload)
        start.assert_not_called()

    def test_open_starts_service_when_no_healthy_service_exists(self):
        output = io.StringIO()
        with mock.patch.object(workbench, "health", side_effect=[None, {"service": workbench.SERVICE_NAME}]), \
             mock.patch.object(workbench, "start_detached", return_value=(12345, self.root / "service.log")) as start, \
             contextlib.redirect_stdout(output):
            self.assertEqual(workbench.command_open(self.args, MODULE_PATH), 0)
        payload = json.loads(output.getvalue())
        self.assertFalse(payload["reused"])
        self.assertEqual(payload["pid"], 12345)
        start.assert_called_once()


class LoggingTests(unittest.TestCase):
    def test_default_log_dir_is_fixed_and_user_scoped(self):
        log_dir = workbench.default_log_dir()
        self.assertEqual(log_dir.name, "logs")
        self.assertEqual(log_dir.parent.name, "html-workbench")
        # Same project base as the vendor cache, so everything lives under one dir.
        self.assertEqual(log_dir, workbench.default_vendor_cache().parents[2] / "logs")

    def test_setup_logging_writes_rotating_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            port = 4399
            logger = workbench.setup_logging(tmp, port)
            logger.info("hello %s", "world")
            log_file = Path(tmp) / f"workbench-{port}.log"
            self.assertTrue(log_file.is_file())
            self.assertIn("hello world", log_file.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
