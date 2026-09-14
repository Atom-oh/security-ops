"""Execute publication and workspace steps without GitHub or model access."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/pr-review.yml"


def steps():
    text = WORKFLOW.read_text()
    matches = list(re.finditer(r"^      - name: (.+)$", text, re.M))
    return {
        match[1]: text[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(text)]
        for index, match in enumerate(matches)
    }


def script(name):
    block = steps()[name]
    run = re.search(r"^        run: \|\n((?:          .*\n|\n)+)", block, re.M)
    if run is None:
        raise AssertionError("No shell block: " + name)
    return "\n".join(line[10:] for line in run[1].splitlines()) + "\n"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.work = self.root / "pr-review"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.head = "a" * 40
        self.environment = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.environment.update(
            GITHUB_ENV=str(self.root / "env"), GITHUB_OUTPUT=str(self.root / "outputs"),
            HEAD_SHA=self.head, PR_NUMBER="18", REPO="example/repository",
            GATE_RESULT="pass", chair_used="Deterministic specialist summary",
            chair_failed="0", panel_responded="",
        )
        fake = self.bin / "gh"
        fake.write_text(
            "#!/usr/bin/env python3\nimport json,pathlib,sys\n"
            f"root=pathlib.Path({str(self.root)!r})\n"
            "with (root/'calls').open('a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
            f"if sys.argv[1]=='api' and '/pulls/' in sys.argv[2]: print({self.head!r})\n"
        )
        fake.chmod(0o755)

    def execute(self, name):
        body = script(name).replace("/tmp/", str(self.root) + "/")
        body = body.replace("${{ github.event.pull_request.head.sha }}", self.head)
        return subprocess.run(
            ["bash", "-eo", "pipefail", "-c", body], cwd=self.root,
            env=self.environment, capture_output=True, text=True, timeout=10,
        )

    def test_tokens_are_only_in_github_client_steps(self):
        text = WORKFLOW.read_text()
        prefix = text[:text.index("    steps:")]
        self.assertNotRegex(prefix, r"(?m)^\s+(?:GH_TOKEN|GITHUB_TOKEN):")
        expected = {
            "Get PR diff (with project-specific filters)",
            "Prepare specialist scope",
            "Post review comment (upsert)",
        }
        found = {name for name, block in steps().items() if "GH_TOKEN:" in block}
        self.assertEqual(found, expected)
        self.assertNotIn("prepare_roles.py", script("Run specialists and conditionally adjudicate findings"))
        self.assertIn("--prepared", script("Run specialists and conditionally adjudicate findings"))

    def test_artifacts_keep_retry_receipts_without_private_inputs(self):
        block = steps()["Preserve specialist scope and execution evidence"]
        self.assertIn("github.run_attempt", block)
        self.assertIn("/tmp/pr-review/slot/*-attempts.json", block)
        self.assertIn("/tmp/pr-review/slot/*-request.json", block)
        self.assertIn("/tmp/pr-review/role-source.json", block)
        self.assertIn("if-no-files-found: error", block)
        for private in ("requests/", "roles/", "project-context.md", "role-diff.txt", "runtime/"):
            self.assertNotIn(private, block)

    def test_fresh_workspace_clears_prior_flags_and_rejects_symlink(self):
        text = WORKFLOW.read_text()
        self.assertLess(text.index("name: Prepare fresh review workspace"), text.index("name: Get PR diff"))
        self.assertLess(text.index("name: Prepare fresh review workspace"), text.index("name: Verify Claude"))
        self.work.mkdir()
        (self.work / "old-preflight.flag").touch()
        self.assertEqual(self.execute("Prepare fresh review workspace").returncode, 0)
        self.assertEqual(list(self.work.iterdir()), [])
        self.work.rmdir()
        target = self.root / "keep"
        target.mkdir()
        self.work.symlink_to(target)
        self.assertNotEqual(self.execute("Prepare fresh review workspace").returncode, 0)
        self.assertTrue(target.is_dir())

    def test_deterministic_comment_never_claims_a_chair_or_missing_reviewers(self):
        (self.root / "review.md").write_text("Approved exclusions only; no model coverage.\nVERDICT: PASS\n")
        result = self.execute("Post review comment (upsert)")
        self.assertEqual(result.returncode, 0, result.stderr)
        body = (self.root / "comment.md").read_text()
        self.assertIn("Deterministic specialist summary", body)
        self.assertIn("Validated specialists: none", body)
        self.assertNotIn("Claude(chair)", body)
        self.assertNotIn("solo", body)
        self.assertIn(self.head, body)
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertTrue(any("--body-file" in call for call in calls))

    def test_stale_head_blocks_publication(self):
        self.environment["HEAD_SHA"] = "b" * 40
        (self.root / "review.md").write_text("Complete report.\nVERDICT: PASS\n")
        result = self.execute("Post review comment (upsert)")
        self.assertNotEqual(result.returncode, 0)
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertEqual(len(calls), 1)
        self.assertFalse((self.root / "comment.md").exists())

    def test_preparation_failure_still_reaches_failure_publication(self):
        directory = self.root / "scripts/pr-review"
        directory.mkdir(parents=True)
        (directory / "run-panel.sh").write_text("exit 2\n")
        (directory / "synthesize.sh").write_text("touch unexpected-chair\nexit 0\n")
        self.environment["PR_TITLE"] = "A test"
        result = self.execute("Run specialists and conditionally adjudicate findings")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "unexpected-chair").exists())
        self.assertTrue((self.root / "review.md").read_text().endswith("VERDICT: FAIL\n"))
        self.assertTrue((self.work / "slot/execution-error.flag").exists())
        self.assertIn("chair_failed=1", (self.root / "env").read_text())
        self.assertEqual(self.execute("Check for blocking issues").returncode, 0)
        self.assertIn("result=fail", (self.root / "outputs").read_text())

    def test_separate_preparation_failure_never_enters_provider_step(self):
        directory = self.root / "scripts/pr-review"
        directory.mkdir(parents=True)
        (directory / "prepare_roles.py").write_text("raise SystemExit(2)\n")
        (directory / "run-panel.sh").write_text("touch unexpected-provider\nexit 0\n")
        (directory / "synthesize.sh").write_text("touch unexpected-chair\nexit 0\n")
        self.environment["PR_TITLE"] = "A test"
        self.assertEqual(self.execute("Prepare specialist scope").returncode, 0)
        self.assertTrue((self.work / "slot/preparation-error.flag").exists())
        result = self.execute("Run specialists and conditionally adjudicate findings")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "unexpected-provider").exists())
        self.assertFalse((self.root / "unexpected-chair").exists())
        self.assertTrue((self.root / "review.md").read_text().endswith("VERDICT: FAIL\n"))
        self.assertEqual(self.execute("Check for blocking issues").returncode, 0)
        self.assertIn("result=fail", (self.root / "outputs").read_text())


if __name__ == "__main__":
    unittest.main()
