"""Review presentation gates preserve schema, custody and provider diagnostics."""

import json
import unittest
from unittest.mock import patch

import role_review
import test_role_review as roles
import test_synthesize_roles as chairs


class ReviewFormatTests(unittest.TestCase):
    def supported_reference_examples(self):
        return (
            "See `src/token.py:42` for token validation.",
            "See `AWS::SecretsManager::Secret` for the resource type.",
            "See `web/lib/token.ts:42-45` for token validation.",
            "See `web/lib/token.ts:42:7` for token validation.",
            "See ``src/token.py:42`` for token validation.",
        )

    def test_supported_reference_delimiters_survive_record_and_aggregate(self):
        for text in self.supported_reference_examples():
            with self.subTest(text=text):
                reply, plan = self.response(text)
                role_review.validate_response(reply, plan, "codex")
                helper = roles.RoleReviewTests()
                helper.setUp()
                self.addCleanup(helper.tearDown)
                helper.prepare()
                evidence = text + "\nPUBLIC_AFTER"
                result = helper.record("codex", helper.response("codex", checks=[{
                    "path": roles.FRONTEND, "evidence": evidence,
                }]))
                self.assertTrue(result["valid"])
                filtered = result["response"]["checks"][0]["evidence"]
                self.assertEqual(filtered.count("`"), text.count("`"))
                self.assertIn("[REDACTED]", filtered)
                self.assertIn("PUBLIC_AFTER", filtered)
                self.assertIn(text[text.rfind("`") + 1:], filtered)
                self.assertEqual(result["response"]["reviewed_paths"], [roles.FRONTEND])
                helper.record("claude-self")
                helper.aggregate()
                self.assertEqual(helper.summary()["mode"], "deterministic")
                self.assertTrue(helper.text("deterministic-review.md").endswith("VERDICT: PASS\n"))

    def test_supported_reference_delimiters_preserve_chair_success(self):
        for text in self.supported_reference_examples():
            with self.subTest(text=text):
                helper = chairs.SynthesisTests()
                helper.setUp()
                self.addCleanup(helper.doCleanups)
                reply = (0, text + "\nPUBLIC_AFTER\nVERDICT: PASS\n", "")
                calls, published = helper.run_chair([reply, reply])
                self.assertEqual(calls, 1)
                self.assertEqual(published.count("`"), text.count("`"))
                self.assertIn("[REDACTED]", published)
                self.assertIn("PUBLIC_AFTER", published)
                self.assertTrue(published.endswith("VERDICT: PASS\n"))

    def test_reference_delimiters_do_not_shorten_an_enclosing_secret_value(self):
        canary = "DELIMITER_PRIVATE_CANARY"
        for value in (
            "prefix`" + canary + "`",
            "`" + canary + "`",
            "prefix`path/token.ts:42`" + canary,
            "prefix`AWS::SecretsManager::Secret`" + canary,
            "prefix`web/lib/token.ts:42-45`" + canary,
        ):
            with self.subTest(value=value):
                original = "password=" + value + "\nPUBLIC_AFTER"
                self.assertNotIn(canary, role_review.scrub(original))
                text = roles.fenced_example(original)
                helper = roles.RoleReviewTests()
                helper.setUp()
                self.addCleanup(helper.tearDown)
                helper.prepare()
                result = helper.record("codex", helper.response("codex", checks=[{
                    "path": roles.FRONTEND, "evidence": text,
                }]))
                self.assertTrue(result["valid"])
                self.assertNotIn(canary, json.dumps(result))
                self.assertIn("PUBLIC_AFTER", json.dumps(result))
                chair = chairs.SynthesisTests()
                chair.setUp()
                self.addCleanup(chair.doCleanups)
                calls, published = chair.run_chair([(0, text + "\nVERDICT: PASS\n", "")])
                self.assertEqual(calls, 1)
                self.assertNotIn(canary, published)
                self.assertIn("PUBLIC_AFTER", published)
                self.assertTrue(published.endswith("VERDICT: PASS\n"))

    def test_reference_boundary_does_not_release_an_attached_value_suffix(self):
        canary = "DELIMITER_PRIVATE_CANARY"
        for reference in ("path/token.ts:42", "AWS::SecretsManager::Secret",
                          "web/lib/token.ts:42-45"):
            with self.subTest(reference=reference):
                original = "`" + reference + "`" + canary + "\nPUBLIC_AFTER"
                self.assertNotIn(canary, role_review.scrub(original))

    def test_complete_primary_fail_cannot_be_cleared_by_format_fallback(self):
        helper = chairs.SynthesisTests()
        helper.setUp()
        self.addCleanup(helper.doCleanups)
        calls, text = helper.run_chair([
            (0, "A blocking candidate remains. `bad code`\nVERDICT: FAIL\n", ""),
            (0, "Fallback would clear it.\nVERDICT: PASS\n", ""),
        ])
        self.assertEqual(calls, 1)
        self.assertTrue(text.endswith("VERDICT: FAIL\n"))
        self.assertNotIn("bad code", text)

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
                     "See token.py:42; token='synthetic'",
                     "`config.password`: 'synthetic'",
                     "`/config/token` = 'synthetic'",
                     "password: !!str synthetic-value",
                     "token: &saved synthetic-value",
                     "config.password: synthetic-value"):
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
