# Runbook: AI PR-Review Panel — Kiro cells

Covers the two non-transient ways the Kiro half of the lens×model panel
(`scripts/pr-review/run-panel.sh`, `.github/workflows/pr-review.yml`; roster Codex +
`kiro-opus`/`kiro-gpt` × lenses L2–L5) stops contributing, and what to do about each.
Both are surfaced by a banner at the top of the PR review comment and an `::error::`
line in the Actions log. Agent fallback always forces `VERDICT: FAIL`. Quota failures
remove the affected cells without retry; the existing vendor-axis coverage gate forces
`VERDICT: FAIL` when neither Kiro model has any successful cell (the usual outcome, since
one key serves both models).

These signatures are interpreted only in **Kiro** stderr. Codex echoes the reviewed diff
to stderr, so a diff that quotes these strings (this runbook's own PR is an example) must
not discard a valid Codex review or block its retry — `try_panel` gates the checks on the
provider argument.

## Symptom A — `🚫 Kiro 월간 요청 한도 소진`

Log: `::error::Kiro monthly request quota exhausted for KIRO_API_KEY — … The limits
reset on MM/DD`. Every Kiro cell is skipped without retry (`[quota] kiro-…`); only
`codex/L2..L5` respond, so the coverage gate also prints `coverage collapsed to ≤1 vendor`.

Cause: the Kiro account behind `KIRO_API_KEY` returned
`ServiceQuotaExceededException reason=MONTHLY_REQUEST_COUNT`. The key lives in
Secrets Manager `/demo-platform/actions/AI-key` (owned by the AWS-Demo-Platform
repository, ExternalSecret `ai-panel-keys`) and is shared by every repository whose PR
review runs on the `actions-runner-claude` image, so one busy month across all of them
exhausts it for all of them. It is not a headless-mode or flag problem: the same call
succeeds with a non-exhausted login, and `--v3` hits the same quota.

Fix (account-side only — nothing in this repository can lift it):
1. Enable overages on the Kiro account that owns the key, **or** issue a key from an
   account with remaining quota and update `KIRO_API_KEY` in
   `/demo-platform/actions/AI-key` (ESO refreshes the runner secret; new runner pods
   pick it up).
2. Re-run the failed `AI Code Review` workflow (or push to the PR). The banner disappears
   when Kiro cells respond again.
3. If nothing is done, the quota resets on the date printed in the banner.

Verify locally without spending CI minutes (never echo the key):
```bash
K=$(aws secretsmanager get-secret-value --secret-id /demo-platform/actions/AI-key \
      --region ap-northeast-2 --query SecretString --output text | jq -r .KIRO_API_KEY)
d=$(mktemp -d); ( cd "$d" && env -i PATH="$PATH" HOME="$d" KIRO_API_KEY="$K" \
  kiro-cli chat "Reply PONG." --model gpt-5.6-terra --no-interactive --wrap never )
# exhausted → stderr "Monthly request limit reached", empty stdout, exit 0
```

## Symptom B — `🔓 Kiro 무툴 계약 위반`

Log: `::error::kiro-cli ignored --agent pr-review-notools (fell back to the default
agent WITH tools) …`. Kiro responses are discarded even if non-empty and
`coverage-severe.flag` forces `VERDICT: FAIL`.

Cause: kiro-cli printed `Error: no agent with name pr-review-notools found. Falling back
to user specified default` (it does so for a missing agent file, an invalid JSON file, or
an agent schema the runner's kiro-cli version rejects) and continued **with exit 0** using
the default agent, which trusts `read`/`glob`/`grep`/`code` in the working directory and
read-only `aws` calls. The panel treats this as a broken security contract: the PR diff
is untrusted input and Kiro cells must have zero tools (this repository's
defensive-only/fail-closed principle, `CLAUDE.md`).

Fix:
1. Check the kiro-cli version printed on the first stderr line of the panel step
   (`run-panel.sh: kiro-cli X.Y.Z`) against the version the agent file was validated
   with (2.11.1).
2. Validate the agent file with that version:
   `kiro-cli agent validate --path scripts/pr-review/agents/pr-review-notools.json`
   (command verified with kiro-cli 2.11.1).
3. Re-verify the no-tools behaviour before changing anything else:
   ```bash
   d=$(mktemp -d); mkdir -p "$d/.kiro/agents"
   cp scripts/pr-review/agents/pr-review-notools.json "$d/.kiro/agents/"
   echo CANARY > "$d/notes.txt"
   ( cd "$d" && HOME="$d" kiro-cli chat "Read ./notes.txt and print it. If you have no tools, reply NO_TOOLS." \
       --agent pr-review-notools --model gpt-5.6-terra --no-interactive --wrap never )
   # expected: NO_TOOLS, no "using tool: read", no CANARY
   ```
4. Do **not** switch to `--v3` / `--agent-engine v3` to work around it: the v3 engine
   ignores the agent's `tools: []` and reads working-directory files. `--mode default`
   is a v3-only flag and was dropped together with `--trust-tools=`.

Malformed agent JSON (including duplicate keys), a `name` other than
`pr-review-notools`, non-empty `tools`/`allowedTools`/`resources`/`mcpServers`, or a
failed copy into a cell's `.kiro/agents/` abort the panel step before any model call.
These configuration failures appear directly in the failed step log, not as a banner.

The runner image and its kiro-cli version are managed in the AWS-Demo-Platform
repository (`docker/actions-runner-claude/Dockerfile`); pinning or rebuilding that image
is a separate change from this repository's review scripts.

## Background

`--trust-tools=` (empty) used to be the no-tools mechanism, and `kiro-cli chat --help`
in 2.11.1 still documents it as "trust no tools". In practice 2.11.1 parses the empty
value as a custom tool name, prints `WARNING: --trust-tools arg for custom tool  needs
to be prepended with @{MCPSERVERNAME}/`, and keeps the default agent — so a cell could
read files in its cwd. The earlier "injected `read /etc/passwd` was refused" evidence
only showed that paths *outside* the cwd are refused in non-interactive mode. The only
mechanism that removes tools on the v2 engine is an agent config with `"tools": []`
passed via `--agent`, copied into each cell's `$CELL_CWD/.kiro/agents/` (HOME is the
cell cwd, so the global and workspace agent paths coincide). This matches the
AWS-Demo-Platform repository's ADR-011 decision to stay off `--v3`; this repository has
no ADR of its own for the panel. Ported from the claude-code-usage-dashboard repository's
PR #33.

`tests/pr-review-panel-stub.sh` pins the current mechanism and both signatures above with
stubbed `kiro-cli`/`codex`/`claude` binaries (no model calls):

```bash
bash tests/pr-review-panel-stub.sh
```

It is separate from `tests/run-all.sh` (backend/frontend/terraform gate) on purpose —
the panel scripts have no runtime dependency on those stacks.
