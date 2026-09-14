"""Offline privacy and original-record parity tests; never invoke a model."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from record_diagnostic import metadata, record_wrapper

SOURCE = Path(os.environ.get("REVIEWED_BASE_ROOT", Path(__file__).resolve().parents[3]))
ENGINE = SOURCE / "scripts/pr-review/role_review.py"
spec = importlib.util.spec_from_file_location("base_diagnostic_tests", ENGINE)
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


class DiagnosticTests(unittest.TestCase):
    def test_safe_metadata_distinguishes_failures_without_any_response_value(self):
        cases = [
            ('private_value\n{}', "malformed_json", "Expecting value", "prose"),
            ('{}\nprivate_value', "malformed_json", "Extra data", "object"),
            ('{"value":"private_value\\q"}', "malformed_json", "Invalid \\escape", "object"),
            ('{"value":"private_value', "malformed_json", "Unterminated string starting at", "object"),
            ('> ```json\n> {"value":"private_value"}\n> ```', None, None, "object"),
            ('{"private_value":1,"private_value":2}', "duplicate_json_key", None, "object"),
            ('{"private_value":NaN}', "nonfinite_json", None, "object"),
            ('> ```json\n> {"value":"private_value"}', "invalid_json_wrapper", None, "fence"),
            ('> \n>', "empty_response", None, "empty"),
        ]
        original = engine.strict_json
        for text, error, message, kind in cases:
            with self.subTest(error=error, message=message, kind=kind):
                result = metadata(text.encode(), engine)
                self.assertNotIn("private_value", json.dumps(result))
                self.assertEqual(set(result), {
                    "byte_length", "parse_response_error", "json_decode_error",
                    "first_content_kind", "ordinary_json_parses",
                    "ordinary_json_parses_but_strict_rejects", "normalized_json_available"})
                self.assertEqual(result["byte_length"], len(text.encode()))
                self.assertEqual(result["parse_response_error"], error)
                self.assertEqual(result["first_content_kind"], kind)
                self.assertEqual(result["json_decode_error"]["msg"]
                                 if result["json_decode_error"] else None, message)
                self.assertEqual(result["ordinary_json_parses_but_strict_rejects"],
                                 error in ("duplicate_json_key", "nonfinite_json"))
                self.assertIs(engine.strict_json, original)
                if message:
                    self.assertEqual(set(result["json_decode_error"]),
                                     {"msg", "line", "column", "offset"})

    def test_positions_use_the_exact_base_transport_and_fence_normalization(self):
        value = '> ```json\n> {"value":"private_value\\q"}\n> ```'
        result = metadata(value.encode(), engine)
        try:
            json.loads('{"value":"private_value\\q"}')
        except json.JSONDecodeError as error:
            self.assertEqual(result["json_decode_error"], {
                "msg": error.msg, "line": error.lineno, "column": error.colno,
                "offset": error.pos})

    def test_original_record_status_and_result_are_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw = root / "raw.diff"
            raw.write_text("diff --git a/check.py b/check.py\n--- a/check.py\n+++ b/check.py\n"
                           "@@ -1 +1 @@\n-old\n+new\n")
            context = root / "context.md"
            context.write_text("Trusted test context.\n")
            template = root / "prepared"
            subprocess.run([sys.executable, str(ENGINE), "prepare", "--work", str(template),
                            "--diff", str(raw), "--context", str(context),
                            "--head", "a" * 40, "--base", "b" * 40], check=True)
            subprocess.run([sys.executable, str(ENGINE), "issue", "--work", str(template),
                            "--tag", "kiro-fable"], check=True)
            receipt = json.loads((template / "slot/kiro-fable-request.json").read_text())
            nonce = receipt["invocation_nonce"]
            response = {"head_sha": "a" * 40, "role": "aws", "scope_complete": True,
                        "reviewed_paths": ["check.py"],
                        "checks": [{"path": "check.py", "evidence": "Checked branch."}],
                        "findings": [], "uncertainties": []}
            stderr = root / "stderr.txt"
            stderr.write_text("")
            for index, body in enumerate((json.dumps(response), '{"value":"private_value')):
                with self.subTest(index=index):
                    output = root / "kiro-fable-response-test"
                    output.write_text(body)
                    plain, wrapped = root / f"plain-{index}", root / f"wrapped-{index}"
                    shutil.copytree(template, plain)
                    shutil.copytree(template, wrapped)
                    def command(work):
                        return [sys.executable, str(ENGINE), "record", "--work", str(work),
                                "--tag", "kiro-fable", "--output", str(output),
                                "--stderr", str(stderr), "--exit-code", "0", "--nonce", nonce]
                    before = output.read_bytes()
                    expected = subprocess.run(command(plain), capture_output=True)
                    wrapper = record_wrapper(subprocess.run, ENGINE, wrapped, engine)
                    actual = wrapper(command(wrapped), capture_output=True)
                    self.assertEqual(expected.returncode, actual.returncode)
                    self.assertEqual(expected.stdout, actual.stdout)
                    self.assertEqual(expected.stderr, actual.stderr)
                    self.assertEqual((plain / "slot/kiro-fable-result.json").read_bytes(),
                                     (wrapped / "slot/kiro-fable-result.json").read_bytes())
                    self.assertEqual(output.read_bytes(), before)
                    report = wrapped / "slot/kiro-fable-parse-metadata.json"
                    self.assertNotIn("private_value", report.read_text())

    def test_diagnostic_write_failure_does_not_replace_record_result(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "work"
            output = work.parent / "kiro-fable-response-test"
            output.write_text("{}")
            (work / "slot/kiro-fable-parse-metadata.json").mkdir(parents=True)
            calls = []
            sentinel = object()
            def original(*args, **kwargs):
                calls.append((args, kwargs))
                return sentinel
            command = [sys.executable, str(ENGINE), "record", "--work", str(work),
                       "--tag", "kiro-fable", "--output", str(output)]
            result = record_wrapper(original, ENGINE, work, engine)(command, check=False)
            self.assertIs(result, sentinel)
            self.assertEqual(calls, [((command,), {"check": False})])


if __name__ == "__main__":
    unittest.main()
