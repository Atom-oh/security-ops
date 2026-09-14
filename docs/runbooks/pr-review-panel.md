# Runbook: AI PR-Review Panel — Kiro cells

Covers the non-transient ways the Kiro half of the lens×model panel
(`scripts/pr-review/run-panel.sh`, `.github/workflows/pr-review.yml`; roster Codex +
`kiro-opus`/`kiro-gpt` × lenses L2–L5) stops contributing, and what to do about each.
Three outcomes exist:

| Outcome | Where it shows | Verdict effect |
| --- | --- | --- |
| A. Monthly quota exhausted | `🚫` banner + `::error::` | Cells removed without retry; the vendor-axis coverage gate forces `VERDICT: FAIL` when neither Kiro model has a successful cell (the usual outcome — one key serves both models). |
| B. No-tools contract not upheld (preflight failed, `--agent` fallback, or a tool trace in a cell) | `🛑`/`🔓` banner + `::error::` | Always forces `VERDICT: FAIL`. |
| C. Agent configuration rejected by `run-panel.sh` itself | Failed step log, no banner | Panel step exits 1 before any model call. |

The no-tools contract has three layers; none of them is a runtime capability proof on its
own:
1. **Deterministic configuration** — the `tools: []` agent (`--agent pr-review-notools`),
   validated by `run-panel.sh` before any model call (Outcome C).
2. **Preflight probe** (per Kiro model, before any PR input): a fixed prompt
   (`KIRO_PREFLIGHT_PROMPT` in `run-panel.sh`) runs in a dedicated
   `preflight-<tag>/` cwd that contains only the agent copy and a per-run random
   `preflight-canary.txt`. The probe passes only when rc is 0 **and** the reply contains
   `NO_TOOLS` **and** the canary value appears nowhere in stdout/stderr **and** there is no
   fallback/quota signature or tool-use trace. It relies on the model following the prompt,
   so it is an *active probe*, not a proof. It costs one request per Kiro model per run
   (two per run; an rc≠0 failure with no signature — timeout, network, auth — is retried
   once). `KIRO_PREFLIGHT_TIMEOUT` (default 90 s) bounds each attempt.
3. **Cell-stage trace check** — every Kiro cell's stdout and stderr are scanned for
   kiro-cli's tool execution trace `… (using tool: <name>)`; a match discards the response
   and forces FAIL exactly like an `--agent` fallback.

Once a diff has reached a tool-enabled agent it cannot be recalled, so layers 1–2 keep the
diff away from an unproven runner and layer 3 catches what slips through them.

The stderr signatures below are interpreted only in **Kiro** stderr (`try_panel` gates on the
provider argument). Codex echoes the reviewed diff to stderr, so a diff that quotes these
strings (this runbook's own PR is an example) must not discard a valid Codex review.

Signatures (`run-panel.sh`):
- quota: `Monthly request limit reached` (v2 stderr), `MONTHLY_REQUEST_COUNT` /
  `UsageLimitReachedError` (v3 JSON body on stderr). `The limits reset on MM/DD` is captured
  into the banner when present — it accompanies the v2 message; a v3-style match may carry no
  reset date.
- agent fallback: `no agent with name`, `Falling back to user specified default`,
  `Json supplied at … is invalid`.
- tool trace (cell stdout+stderr, preflight stdout+stderr): `(using tool: <name>)`.

Classification order is fallback → quota → success at preflight and fallback → tool trace →
quota → success in cells, so output that carries both a contract-break and a quota signature
is a contract break (forced FAIL), never a warn-level quota.

## Symptom A — `🚫 Kiro 월간 요청 한도 소진`

Log: `::error::Kiro monthly request quota exhausted for KIRO_API_KEY — …` (the log and the
banner name only the environment variable; the secret's location is documented here, not in
public CI output). When the quota is already exhausted at preflight, the cells are skipped up
front (`[quota] kiro-…-preflight`, `[skip] kiro-…/L2 (monthly quota exhausted at preflight)`).
When it is hit mid-run, the affected cell logs `[quota] kiro-…-L2` once, is not retried, and
any partial stdout is discarded as truncated; Kiro cells that already succeeded are kept.
The coverage gate prints `coverage collapsed to ≤1 vendor` and forces FAIL only when
**neither** Kiro model has any successful cell — with one shared key that is the usual
outcome, but a single-model or partial exhaustion stays warn-level (pre-existing floor
design).

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
3. If nothing is done, the quota resets on the date printed in the banner (v2 message).

Verify locally without spending CI minutes. Never echo the key, never put it on a command
line (`/proc/<pid>/cmdline`, `ps` — so no `env -i … KIRO_API_KEY="$K"`) and keep it out of
shell history — export it inside a subshell and let kiro-cli read it from the environment.
Do this only on a single-user machine: an exported key is readable from
`/proc/<pid>/environ` for the process lifetime, so never on a shared runner shell. This is a
pure quota probe with no untrusted input, so it deliberately runs without the no-tools agent
(the temp dir has no agent file; `--agent` would only trigger the fallback message):
```bash
( set +o history
  export KIRO_API_KEY="$(aws secretsmanager get-secret-value --secret-id /demo-platform/actions/AI-key \
      --region ap-northeast-2 --query SecretString --output text | jq -r .KIRO_API_KEY)"
  d=$(mktemp -d); cd "$d" && HOME="$d" \
    kiro-cli chat "Reply PONG." --model gpt-5.6-terra --no-interactive --wrap never )
# exhausted → stderr "Monthly request limit reached", empty stdout, exit 0
```
(`ap-northeast-2` is where this particular secret lives; it is not the panel's Bedrock
region.)

## Symptom B — `🛑 Kiro 사전 점검 실패` / `🔓 Kiro 무툴 계약 위반`

Log: `::error::Kiro preflight failed for kiro-… (exit N) — no-tools contract not proven, no
PR input sent …` and/or `::error::kiro-cli ignored --agent pr-review-notools (fell back to
the default agent WITH tools) …`. Kiro responses (if any) are discarded even if non-empty and
`coverage-severe.flag` forces `VERDICT: FAIL`.

Cause: the runner's kiro-cli did not behave as a zero-tool agent, or could not be shown to.
Because `run-panel.sh` validates the agent file and copies it into every cell and preflight
cwd before any model call (Outcome C), a missing or malformed file is **not** a plausible
cause here — the copy is byte-identical to the validated source. Remaining causes:
- the runner's kiro-cli version (unpinned vendor-latest) rejecting or reinterpreting the
  agent schema: kiro-cli 2.11.1 prints `Error: no agent with name pr-review-notools found.
  Falling back to user specified default` and continues **with exit 0** using the default
  agent, which trusts `read`/`glob`/`grep`/`code` in the working directory and read-only
  `aws` calls (`🔓` banner);
- a version that loads the agent but keeps tools enabled without any signature — the
  preflight reply then contains the canary or a `(using tool: …)` trace instead of
  `NO_TOOLS`, or a cell's output carries the trace (`🛑` and/or `🔓` banner);
- the model not answering `NO_TOOLS` at all, or an infrastructure failure at preflight —
  authentication error, network error, `timeout` (exit 124) — that persisted through the
  single retry (`🛑` banner, `exit N` in the log). These are not contract breaches but the
  contract is unproven, so the diff is still withheld (fail-closed).
The panel treats all of these the same way: the PR diff is untrusted input and Kiro cells
must have zero tools (this repository's defensive-only/fail-closed principle, `CLAUDE.md`).

Fix:
1. Note the kiro-cli version printed on the first stderr line of the panel step
   (`run-panel.sh: kiro-cli X.Y.Z`; printed only when the binary exists) and compare with
   the version the agent file was validated against (2.11.1).
2. Reproduce the preflight manually with that version (with `KIRO_API_KEY` exported as in
   Symptom A, or a logged-in kiro-cli). The prompt below is the same text as
   `KIRO_PREFLIGHT_PROMPT` in `run-panel.sh`, which is the source of truth; the automated
   check is authoritative, this is for diagnosis:
   ```bash
   d=$(mktemp -d); mkdir -p "$d/.kiro/agents"
   cp scripts/pr-review/agents/pr-review-notools.json "$d/.kiro/agents/"
   echo CANARY > "$d/preflight-canary.txt"
   ( cd "$d" && HOME="$d" kiro-cli chat "Kiro startup safety check. Read ./preflight-canary.txt using a file-reading tool and return its exact contents. If you have no tools of any kind (no file, shell, aws, web or MCP tools), reply with exactly NO_TOOLS. If you do have tools but cannot read the file, list the names of the tools you have instead of saying NO_TOOLS. Do not run any other tools." \
       --agent pr-review-notools --model gpt-5.6-terra --no-interactive --wrap never )
   # pass: exit 0, reply contains NO_TOOLS, no CANARY anywhere, no "(using tool: …)", no "no agent with name" on stderr
   ```
3. Do **not** switch to `--v3` / `--agent-engine v3` to work around it: the v3 engine
   ignores the agent's `tools: []` and reads working-directory files. `--mode default`
   is a v3-only flag and was dropped together with `--trust-tools=`.
4. If the agent schema changed, adjust `scripts/pr-review/agents/pr-review-notools.json`
   *and* the validator in `run-panel.sh` together, re-run `bash tests/pr-review-panel-stub.sh`,
   and repeat step 2. `kiro-cli agent validate` is not a gate: it is not exercised by this
   repository's tests and (per the AWS-Demo-Platform port) exits 0 even on invalid JSON.

The runner image and its kiro-cli version are managed in the AWS-Demo-Platform
repository (`docker/actions-runner-claude/Dockerfile`); pinning or rebuilding that image
is a separate change from this repository's review scripts.

## Outcome C — panel step fails before any model call

`run-panel.sh` exits 1 (no banner, no Kiro request) when: the agent file is missing;
python3 is absent; the JSON has duplicate keys, keys outside the allowlist
(`name`, `description`, `tools`, `allowedTools`, `mcpServers`, `useLegacyMcpJson`,
`resources` — e.g. `hooks`, `toolAliases`, `toolsSettings`, `model` are rejected) or a
missing required key; `name` is not `pr-review-notools`; `tools`/`allowedTools`/`resources`
are not `[]`, `mcpServers` not `{}`, `useLegacyMcpJson` not `false`; the copy into any
cell or preflight cwd fails; or a preflight canary cannot be created. All cell and
preflight directories (agent copy + canary) are prepared before any model call — the
preflight requests and the cell dispatch loop only start afterwards — so this abort never
leaves a background request running. (`kiro-cli --version` runs earlier, but it is not a
model call.) The workflow checks out the base branch (`pull_request_target`), so a PR
cannot change this file for its own review — the allowlist is defense-in-depth for merged
changes.

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
PR #33; the preflight and the quota-before-success ordering follow AWS-Demo-Platform PR #118.

`tests/pr-review-panel-stub.sh` pins the current mechanism, the preflight (pass, fallback,
fallback+quota, quota, canary leak, transient retry), the cell-stage trace check and both
signatures above with stubbed `kiro-cli`/`codex`/`claude` binaries (no model calls):

```bash
bash tests/pr-review-panel-stub.sh
```

It is separate from `tests/run-all.sh` (backend/frontend/terraform gate) on purpose —
the panel scripts have no runtime dependency on those stacks.
