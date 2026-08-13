import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "service" / "server" / "validate_html.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures" / "validator"
SPEC = importlib.util.spec_from_file_location("validate_html", MODULE_PATH)
validator = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = validator
SPEC.loader.exec_module(validator)


def validate_fixture(name):
    path = FIXTURES / name
    return validator.validate_file(path)


class ValidatorTests(unittest.TestCase):
    def test_safe_interactive_page_has_no_findings(self):
        result = validate_fixture("safe-interactive.html")
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"], {"error": 0, "warning": 0, "info": 0})

    def test_structural_risks_are_reported_from_js_and_css(self):
        result = validate_fixture("risky-structural.html")
        rules = {issue["rule"] for issue in result["warnings"]}
        self.assertTrue(result["ok"])
        self.assertEqual(rules, {
            "broad-dom-rewrite",
            "indexed-node-lookup",
            "per-node-event-binding",
            "position-dependent-css-selector",
            "position-dependent-js-selector",
            "structural-dom-traversal",
        })
        self.assertTrue(all(issue["line"] > 0 for issue in result["warnings"]))

    def test_contract_errors_fail_validation(self):
        result = validate_fixture("invalid-contract.html")
        rules = {issue["rule"] for issue in result["errors"]}
        self.assertFalse(result["ok"])
        self.assertEqual(rules, {
            "dangerous-url",
            "duplicate-workbench-id",
            "missing-interaction-target",
        })

    def test_incomplete_document_fails_validation(self):
        result = validate_fixture("incomplete-fragment.html")
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["rule"], "incomplete-document")

    def test_external_script_is_informational(self):
        source = """<!doctype html><html><head><script src=\"https://example.com/app.js\"></script></head><body></body></html>"""
        result = validator.validate_source(source)
        self.assertTrue(result["ok"])
        self.assertEqual(result["info"][0]["rule"], "external-script-not-inspected")

    def test_strict_single_file_mode_rejects_referenced_dependencies(self):
        normal = validate_fixture("not-self-contained.html")
        strict = validator.validate_file(FIXTURES / "not-self-contained.html", require_self_contained=True)
        self.assertTrue(normal["ok"])
        self.assertFalse(strict["ok"])
        self.assertEqual(
            {issue["rule"] for issue in strict["errors"]},
            {"non-self-contained-resource"},
        )
        self.assertEqual(len(strict["errors"]), 5)

    def test_target_can_resolve_regular_html_id_with_hash_prefix(self):
        source = """<!doctype html><html><head></head><body><button data-target=\"#panel\">Open</button><div id=\"panel\"></div></body></html>"""
        result = validator.validate_source(source)
        self.assertTrue(result["ok"])
        self.assertEqual(result["errors"], [])

    def test_structural_data_target_is_a_warning_not_an_error(self):
        source = """<!doctype html><html><head></head><body><button data-target=\".panel > div\">Open</button><div class=\"panel\"><div></div></div></body></html>"""
        result = validator.validate_source(source)
        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"][0]["rule"], "non-stable-interaction-target")

    def test_warns_about_inline_event_handlers(self):
        source = """<!doctype html><html><head></head><body><button onclick=\"switchMode('daemon')\">Daemon</button></body></html>"""
        result = validator.validate_source(source)
        self.assertTrue(result["ok"])
        self.assertEqual(result["warnings"][0]["rule"], "inline-event-handler")

    def test_empty_workbench_id_is_an_error(self):
        source = """<!doctype html><html><head></head><body><div data-wb-id></div></body></html>"""
        result = validator.validate_source(source)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["rule"], "empty-workbench-id")

    def test_duplicate_html_id_is_an_error(self):
        source = """<!doctype html><html><head></head><body><div id=\"panel\"></div><div id=\"panel\"></div></body></html>"""
        result = validator.validate_source(source)
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["rule"], "duplicate-html-id")

    def test_missing_file_returns_machine_readable_error(self):
        result = validator.validate_file(FIXTURES / "missing.html")
        self.assertFalse(result["ok"])
        self.assertEqual(result["errors"][0]["rule"], "file-unreadable")

    def test_cli_exit_codes_and_json_output(self):
        safe = subprocess.run(
            [sys.executable, str(MODULE_PATH), str(FIXTURES / "safe-interactive.html")],
            check=False,
            capture_output=True,
            text=True,
        )
        invalid = subprocess.run(
            [sys.executable, str(MODULE_PATH), str(FIXTURES / "invalid-contract.html")],
            check=False,
            capture_output=True,
            text=True,
        )
        strict = subprocess.run(
            [sys.executable, str(MODULE_PATH), "--require-self-contained", str(FIXTURES / "not-self-contained.html")],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(safe.returncode, 0)
        self.assertTrue(json.loads(safe.stdout)["ok"])
        self.assertEqual(invalid.returncode, 1)
        self.assertFalse(json.loads(invalid.stdout)["ok"])
        self.assertEqual(strict.returncode, 1)
        self.assertEqual(len(json.loads(strict.stdout)["errors"]), 5)

    def test_current_workbench_sample_is_accepted_with_css_warnings(self):
        result = validator.validate_file(PROJECT_ROOT / "tests" / "fixtures" / "sample.html")
        self.assertTrue(result["ok"])
        self.assertEqual(
            {issue["rule"] for issue in result["warnings"]},
            {"position-dependent-css-selector"},
        )

    def test_built_skill_contains_the_same_validator(self):
        packaged = PROJECT_ROOT / "skill" / "html-workbench" / "scripts" / "validate_html.py"
        self.assertTrue(packaged.exists())
        self.assertEqual(packaged.read_bytes(), MODULE_PATH.read_bytes())


if __name__ == "__main__":
    unittest.main()
