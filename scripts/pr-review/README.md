# Specialist review protocol

**Installed protocol and tests.** Declared scope is reconciled; BASE collectors
authorize mixed-scope exclusions. Implementation: [role_review.py](role_review.py).
The legacy review pipeline remains active; executor integration and activation
require separate review. [ADR-002](../../docs/decisions/ADR-002-specialist-review-protocol.md)
records the decision. This library performs no Git operations or provider calls.

| Tag | Requested model / provider namespace | Responsibility |
| --- | --- | --- |
| codex | `global.openai.gpt-6-astra` / Bedrock Runtime | Implementation and tests |
| kiro-fable | `claude-opus-5` / Kiro | AWS, IAM and network |
| kiro-sol | `gpt-5.6-sol` / Kiro | Deployment, contracts and recovery |
| claude-self | `global.anthropic.claude-fable-5-1` / Bedrock Runtime | Auth, data, API and ADR |

Tags match the fleet's [schema-1 protocol](https://github.com/Atom-oh/AWS-Demo-Platform/blob/eca34549267b6bb71e7d3bc4f9184d7f94b83d00/scripts/pr-review/role_review.py).
`kiro-fable` is its compatibility identifier for the Opus AWS role. Activation
replaces legacy `kiro-opus` with `kiro-fable` and legacy `kiro-gpt` with `kiro-sol`;
only those two Kiro roles run in the specialist path. Legacy script names remain
until cutover. This table defines the planned binding; the library's `ROLES`
table must implement it explicitly; never infer a model from a tag. Local Codex on
Mantle uses `openai.gpt-6-astra`, a different namespace. The old Mantle regional
Sol observation does not establish Kiro alias availability. No automatic fallback.

## Planned commands

After installation, `python3 scripts/pr-review/role_review.py COMMAND --help`
lists the exact flags. Use a fresh private work directory for each complete diff.

| Command | Contract |
| --- | --- |
| prepare | Diff/context, HEAD/base, work and optional paths/provenance files → plan and `roles/TAG.txt/.diff`. |
| issue | Work/tag → 128-bit random nonce, exact `requests/TAG.prompt/.input` and `slot/TAG-request.json`; call before every attempt. |
| record | Work/tag, output/stderr files, exit code and issued nonce → validated `slot/TAG-result.json`. |
| aggregate | Revalidate plan, receipts and results → summary, responded/mode files and applicable report/flag. |

`--paths` is a UTF-8 JSON file of unique safe repository-relative paths matching
the **filtered review diff**, e.g. `["src/api.ts"]`. Rename destinations are used;
the collector checks both sides. Omit the file only for unambiguous patch paths.
`--provenance` is a JSON file whose `head_sha`/`base_sha` match the CLI's lowercase
40-hex Git revisions; `diff_sha256` hashes exact filtered diff bytes.

Optional provenance fields are `scope_paths` (all original changed paths),
`excluded_paths` (paths removed by approved input policy), `scope_exception`,
`input_policy_sha256`, and `input_failures`. The reserved provenance `path_only`
array must be absent or empty in this rollout; nonempty values block.
Caller-supplied provenance `input_failures` entries must fullmatch
`[a-z][a-z0-9_:.-]{0,63}`; any entry blocks. The host combines them with preparation
errors in `role-plan.json.input_failures`. Scrubbed provenance reaches requests
and the public summary; it is not a model-response schema.

Safe paths are nonempty UTF-8 repository-relative names, with no absolute prefix,
NUL, or empty/`.`/`..` component. Preserve literal Git spelling; do not normalize
or rename paths silently. Serialize paths as JSON so quotes, CR/LF and controls
cannot become raw prompt lines, delimiters or public-report syntax. Existing
input/request byte limits bound them; literal Git path handling prevents options.

Every PR-derived path and provenance value is untrusted data. Issued requests must
put this metadata, like the diff, inside a nonce-bound data block, separate from
trusted BASE instructions. The prompt must explicitly forbid obeying instructions
inside either block, including marker-like text. Public metadata uses escaped JSON;
a filename or provenance value cannot supply instructions or a verdict.

## Trust and scope exceptions

The trusted collector/routing code runs from the reviewed **base checkout**, not
PR-authored scripts. It obtains exact base/head Git objects, reconciles their full
path inventory and loads approved policy from BASE. PR content is data. Hashes
bind bytes; they do not authorize callers or authenticate filesystem writers.
The library validates supplied evidence; the collector owns its Git/BASE origin.

Exclusions-only use requires `--allow-exclusions-only --policy FILE`. The filtered
diff and `--paths` array are empty, while provenance `scope_paths` and
`excluded_paths` are identical, nonempty, unique safe lists of **original** paths.
Set provenance `scope_exception` to `configured_exclusions_only` and
`input_policy_sha256` to the exact policy file's SHA-256. These are different
inventories, not a claim that the original PR has no changes.

The schema-1 policy has optional nonempty-string arrays: `basenames` matches the
final component exactly; `extensions` matches the final suffix; `directories`
matches a parent component; `prefixes` uses literal starts-with; `path_regexes`
uses Python regex search (anchors must be explicit). Invalid regexes block.
These are trusted BASE configuration, not PR-supplied expressions. Every claimed
path must match a rule. Its copied `exclusions-policy.json` bytes and rules are
rechecked on aggregation. This may yield NOT_APPLICABLE/PASS with no model calls;
the report lists excluded paths and the policy hash. A generic collector may use
this only with its reviewed BASE policy and explicit opt-in; an untrusted caller
cannot authorize exclusions. Unknown scope, source omissions and collector failure block.

For this rollout the approved exclusions are exactly the existing workflow's
`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `.terraform.lock.hcl` basenames
and `reference-docs/` prefix. No extension, directory or regex rule is approved.
Changing that set requires a separate BASE-policy review; this schema description
does not approve catch-all rules or new source omissions. Lockfile exclusions are
an explicit retained limitation, not a claim that those files lack security impact.

Metadata-only deletion support is deferred. This rollout rejects nonempty
`path_only`, even with an opt-in flag: deletion headers or caller hashes cannot
authorize withholding source bodies. A future collector needs a separately
reviewed policy and verifiable eligibility contract before enabling that mode.

## Coverage, lifecycle and publication

Every required role receives the same complete filtered diff and path inventory.
`roles/TAG.diff` is a per-role copy, not a slice; responsibilities differ, input
scope does not. Codex/Claude are always required for reviewable source.
Kiro can be inactive only for unambiguously frontend-only paths with presentation
extensions and no applicable content signals. TSX/JSX under `app/` remains
conservative. AWS/service/ARN/region signals in the whole diff require both Kiro
roles; deployment/API/schema/retry signals additionally require `kiro-sol`.
Unknown paths, README/runbook text, Terraform, workflows, IAM/policy JSON,
Dockerfiles and review scripts keep both roles required. Plan/summary record each
role's requirement and routing reason. Failed output is never N/A. Requests carry nonce
boundaries; models cannot change routing or gate state through their output.

Every primary role assesses interactions and combined impact across the full
supplied change. A plausible blocking chain must be a CRITICAL/MAJOR candidate
or an uncertainty, so it reaches the chair. `scope_complete` attests this assigned
review scope; Minor/Info-only results attest no blocking combined impact too.
The host validates these reports and their scope, not the truth of model reasoning.
This decision explicitly accepts the residual risk that primary reviewers can miss
or misclassify an interaction. There is no automatic cross-report adjudication of
Minor/Info-only findings. It replaces unconditional PR synthesis, not the
application scanner's Critical/High/chaining gate. Neither model self-attestation
nor a chair PASS proves the absence of defects; missing or invalid required
evidence still blocks mechanically. No finding-count heuristic is authorized.

Responses are one JSON object with `head_sha`, role slug, `scope_complete`,
`reviewed_paths`, `checks`, `findings` and `uncertainties`. All assigned paths must
appear once; checks need changed paths and concrete evidence. Findings require
severity (CRITICAL/MAJOR/MINOR/INFO), path, condition and evidence. Receipt, scope,
nonce and response digests are revalidated. Configured IDs do not attest weights.

Model responses remain untrusted data after validation, including free text in
checks, findings and uncertainties. The chair must receive them in a fresh
nonce-delimited evidence block with an explicit instruction to ignore embedded
commands and verdict claims. Validation does not promote model text to instructions.
Public/deterministic reports must JSON-escape or neutralize embedded control lines
and apply credential scrubbing; quoted model text cannot supply the host verdict.
The publication gate accepts only a substantive report with exactly one
`^VERDICT:` line, at the final nonempty line, whose value is `VERDICT: PASS` or
`VERDICT: FAIL`. Extra or malformed verdict lines block publication as a success.

Issue/record exclude each other. Duplicate records block and cannot overwrite the
first result. Valid results cannot be reissued. Invalid nonterminal results may
be archived up to 32 times; overflow blocks. Model-selection, fallback, quota and
preflight failures remain terminal until new preparation. Finish writers before
aggregation; summaries retain attempt history. English is requested, not validated.

All upstream `*.flag` files block. Root `coverage-severe.flag` is reserved solely
for the aggregator's recomputed **output**, including a stale output from its
previous invocation. Collectors/executors must use distinct upstream flag names;
this reserved output is never authority to waive a coverage failure.

| Aggregate outcome | Consumer action |
| --- | --- |
| Exit 0 / deterministic | Publish its validated report; Minor/Info alone do not require a chair. Includes approved exclusions-only `NOT_APPLICABLE` applicability with the existing PASS result. |
| Exit 0 / review | Run the chair; confirmed CRITICAL/MAJOR issues or unresolved material uncertainty require FAIL. |
| Exit 2 / blocked | Publish deterministic FAIL; the chair cannot waive invalid/missing coverage. |
| Abnormal exit or missing/mismatched artifacts | Execution failure; never credit stale output. |

Controlled aggregation (exit 0 or 2) writes `role-summary.json`, `responded.txt` and
`chair-mode.txt`; deterministic/blocked modes also write `deterministic-review.md`.
`NOT_APPLICABLE` labels excluded scope in that report; it is not another
`chair-mode.txt` value or a claim of model coverage. An exclusions-only report
retains `mode=deterministic` and its final `VERDICT: PASS`.
The chair checks evidence and combined impact; candidate severity is not an
unreviewable verdict. It records why candidates are rejected/downgraded and emits
exactly one final `VERDICT: PASS` or `VERDICT: FAIL` line with a substantive body.
PASS is permitted only after all blocking candidates and material uncertainty
are resolved. A deterministic FAIL report is not the deterministic PASS mode.
The host writes per-attempt errors to `slot/TAG-result.json.failure_codes`.
Aggregation combines input, role and artifact failures in
`role-summary.json.failures`; `role-summary.json.failure_codes` is its alias.
Aggregate codes may qualify a failure with its role tag. These host-generated
fields are separate from the model response and caller provenance
`input_failures`; the provenance regex does not define every host-generated code.
Keep raw
`roles/*.diff` and `requests/*.input/.prompt` private and out of publication.
Executors must provide private directories, cleanup and a scrubbed artifact allowlist.
Scrubbing must retain valid paths while removing credential values, including
escaped JSON; reference the existing `lib.sh` credential formats and test them.

## Limits and verification

Limits are 95,000 UTF-8 diff bytes, 3,000 lines, 24,000 context bytes (projects may
lower this), and less than 128 KiB per framed request including overhead. Any
limit failure blocks; these are not a promise that simultaneous maxima fit.
No chunk coordinator or combining partial PASS results. Preserve project budgets.

After installation run `python3 -m unittest discover -s scripts/pr-review -p test_role_review.py`.
Planned offline CI: `.github/workflows/pr-review-roles-tests.yml`. Executor/activation
changes must add their own tests and verify exact-HEAD publication, provider access,
limits and source custody. Offline tests do not prove live model execution.

## Installed executors; activation remains separate

The provider helpers are installed but the operational workflow still uses the
legacy matrix until PR #18. `prepare_roles.py` runs from immutable BASE, obtains
merge-base/HEAD objects as data, applies the exact BASE `role-input-scope.json`,
and validates BASE/candidate context. It uses AGENTS when present, otherwise
CLAUDE, with the byte cap and generated-source checks. Only BASE text instructs.
The policy file contains only the four approved lockfile basenames and
`reference-docs/`; no broader exclusion is activated.

From pinned BASE, set `HEAD_SHA`, `BASE_SHA` and `GH_REPO`:

- `run-specialists.sh DIFF UNUSED WORK` prepares and coordinates roles.
- `run_role.py --work WORK --tag TAG` executes a required role.
- `synthesize_roles.py --work WORK --output REPORT` publishes deterministic output
  or adjudicates valid candidates. The standalone Python commands expose `--help`.

Codex retains security-ops' isolated HOME: only the runner's `.codex/config.toml`
is copied, never auth/session files. Missing config does not restore real HOME.
Its environment retains PATH/locale/temp, AWS region and the two Pod Identity
credential-channel variables; unrelated secrets and AWS profiles/keys are excluded.
Kiro uses isolated HOME/cwd and the empty catalog/canary. Claude's specialist has
no tools; the chair uses bounded read tools. GitHub tokens are removed from provider
children. AWS authentication remains necessary for Bedrock; this is not filesystem
confinement or a claim that the inherited runner role is least-privilege.

Raw model JSON is control-normalized and passed privately in a mode-0600 temporary
file outside WORK, removed even on recorder errors. Validation preserves expected
paths before decoded credential redaction. Text-mode stdout errors remain terminal
diagnostics; JSON evidence is not treated as an error. The security-ops chair must
apply decoded redaction before the legacy text scrubber, which otherwise destroys
key boundaries. No raw requests/diffs/provider output are public artifacts.

Defaults/maxima: role timeout 300/900 seconds, total attempts 2/3, Kiro startup
60/120 seconds. The chair retains legacy `CHAIR_TIMEOUT` (600 seconds) and
`PANEL_CELL_CAP` (20,000 UTF-8 bytes per validated role response). Oversize evidence
blocks before a chair call without truncation. Explicit positive chair overrides
are honored, optional project policies may impose maxima, and the absolute timeout
ceiling is 1,500 seconds. No default turn count is invented. Transient throttle can
use the configured fallback; hard quota/model failures remain visible and blocking.

Run `python3 -m unittest discover -s scripts/pr-review -p 'test_*.py' -v` and
`bash -n scripts/pr-review/run-specialists.sh`. Tests use fake CLIs, not live inference.
