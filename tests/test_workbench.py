import importlib.util
import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
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

    def test_rejects_file_outside_root(self):
        outside = Path(self.temp.name).parent / "outside-workbench.html"
        outside.write_text(SAMPLE_HTML, encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        query = urllib.parse.urlencode({"file": str(outside)})
        with self.assertRaises(urllib.error.HTTPError) as context:
            urllib.request.urlopen(self.base + f"/api/document?{query}", timeout=2)
        self.assertEqual(context.exception.code, 403)

    def test_serves_vendor_assets_locally(self):
        route = workbench.VENDOR_ASSETS["grapes.min.js"]["route"]
        with urllib.request.urlopen(self.base + route, timeout=2) as response:
            self.assertEqual(response.read(), b"test-grapes.min.js")
            self.assertIn("immutable", response.headers["Cache-Control"])


if __name__ == "__main__":
    unittest.main()
