"""Review presentation gates preserve schema, custody and provider diagnostics."""

import json
import unittest
from unittest.mock import patch

import role_review
import test_role_review as roles
import test_synthesize_roles as chairs


class ReviewFormatTests(unittest.TestCase):
    def response(self, text):
        path = "src/token.py"
        plan = {"head_sha": "a" * 40, "roles": {"codex": {
            "role": "implementation", "paths": [path]}}}
        reply = {"head_sha": plan["head_sha"], "role": "implementation",
                 "scope_complete": True, "reviewed_paths": [path],
                 "checks": [{"path": path, "evidence": text}],
                 "findings": [], "uncertainties": []}
        return reply, plan

    def test_supported_prose_citations_and_fenced_code(self):
        for text in (
            "Authorization: the caller is checked.",
            "See [token.py](src/token.py:42) for the checked call.",
            "Checked `src/token.py`: the caller is checked.",
            "Example:\n```json\n{\"token\":\"synthetic\"}\n```",
        ):
            with self.subTest(text=text):
                reply, plan = self.response(text)
                role_review.validate_response(reply, plan, "codex")

    def test_invalid_examples_cannot_supply_complete_coverage(self):
        for text in ("Run `echo hello`.", "Set `token` = 'synthetic'.",
                     "Run `first\nsecond`.", "```text\nunclosed",
                     "See token.py:42; token='synthetic'"):
            for field in ("check", "finding", "uncertainty"):
                with self.subTest(text=text, field=field):
                    reply, plan = self.response("Checked the caller.")
                    if field == "check":
                        reply["checks"][0]["evidence"] = text
                    elif field == "finding":
                        reply["findings"] = [{"severity": "MAJOR", "path": "src/token.py",
                                              "condition": "On change", "evidence": text}]
                    else:
                        reply["uncertainties"] = [text]
                    with self.assertRaisesRegex(role_review.Invalid, "^unsupported_review_format$"):
                        role_review.validate_response(reply, plan, "codex")

    def test_fenced_json_keeps_named_value_masking(self):
        helper = roles.RoleReviewTests()
        helper.setUp()
        self.addCleanup(helper.tearDown)
        helper.prepare()
        canary = "FENCED_NAMED_PRIVATE_CANARY"
        text = "```json\n" + json.dumps({
            "name": "password:admin", "value": canary, "public": "PUBLIC_KEEP",
        }) + "\n```"
        result = helper.record("codex", helper.response("codex", checks=[{
            "path": roles.FRONTEND, "evidence": text}]))
        self.assertTrue(result["valid"])
        self.assertNotIn(canary, json.dumps(result))
        self.assertIn("PUBLIC_KEEP", json.dumps(result))

    def test_chair_rejects_invalid_format_and_keeps_quota_terminal(self):
        helper = chairs.SynthesisTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        reply = (0, "Run `echo synthetic-private`.\nVERDICT: PASS\n", "")
        calls, text = helper.run_chair([reply, reply])
        self.assertEqual(calls, 2)
        self.assertTrue(text.endswith("VERDICT: FAIL\n"))
        self.assertNotIn("synthetic-private", text)
        calls, text = helper.run_chair([
            (0, reply[1], "Error: quota exceeded"),
            (0, "Must not run.\nVERDICT: PASS\n", ""),
        ])
        self.assertEqual(calls, 1)
        self.assertTrue(text.endswith("VERDICT: FAIL\n"))

    def test_chair_requires_original_and_filtered_verdict_and_format(self):
        helper = chairs.SynthesisTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        original = "Checked the caller.\nVERDICT: FAIL\nVERDICT: PASS\n"
        with patch.object(helper.module, "scrub_decoded",
                          return_value="Checked the caller.\nVERDICT: PASS\n"):
            _, text = helper.run_chair([(0, original, ""), (0, original, "")])
        self.assertTrue(text.endswith("VERDICT: FAIL\n"))


if __name__ == "__main__":
    unittest.main()
