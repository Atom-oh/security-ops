# Specialist review protocol

**Planned contract:** the offline library and tests arrive in the next PR.
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
`excluded_paths` (paths removed by approved input policy), `path_only` (disclosed
metadata-only deletions), `scope_exception`, `input_policy_sha256`, and
`input_failures`. Failure codes must fullmatch `[a-z][a-z0-9_:.-]{0,63}`; any code
blocks. The plan carries scrubbed provenance into requests and the public summary.

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

The schema-1 policy has optional string arrays `basenames`, `extensions`,
`directories` (parents only), `prefixes` and `path_regexes`. Every claimed path
must match a rule. Its copied `exclusions-policy.json` bytes and rules are
rechecked on aggregation. This may yield NOT_APPLICABLE/PASS with no model calls;
the report lists excluded paths and the policy hash. A generic collector may use
this only with its reviewed BASE policy and explicit opt-in; an untrusted caller
cannot authorize exclusions. Unknown scope, source omissions and collector failure block.

`path_only` separately requires `--allow-metadata-only`. Entries must be unique
safe paths in the patch, with a deletion `index` header containing a nonzero old
OID and an all-zero new OID (abbreviated Git OIDs are supported). This preserves a
controlled metadata-only deletion interface: the collector must prove eligibility
under reviewed BASE policy and the report discloses that deleted bodies were not
reviewed. The generic Git collector does not use this mode.

## Coverage, lifecycle and publication

Every required role reviews its complete assigned diff. Codex/Claude are required
for reviewable source; only trusted routing can deactivate irrelevant Kiro roles.
Unknown scope is conservative. Failed output is never N/A. Requests carry nonce
boundaries; models cannot change routing or gate state through their output.

Responses are one JSON object with `head_sha`, role slug, `scope_complete`,
`reviewed_paths`, `checks`, `findings` and `uncertainties`. All assigned paths must
appear once; checks need changed paths and concrete evidence. Findings require
severity (CRITICAL/MAJOR/MINOR/INFO), path, condition and evidence. Receipt, scope,
nonce and response digests are revalidated. Configured IDs do not attest weights.

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
| Exit 0 / deterministic | Publish its validated report; Minor/Info alone do not require a chair. |
| Exit 0 / review | Run the chair; confirmed CRITICAL/MAJOR issues or unresolved material uncertainty require FAIL. |
| Exit 2 / blocked | Publish deterministic FAIL; the chair cannot waive invalid/missing coverage. |
| Abnormal exit or missing/mismatched artifacts | Execution failure; never credit stale output. |

Controlled aggregation (exit 0 or 2) writes `role-summary.json`, `responded.txt` and
`chair-mode.txt`; deterministic/blocked modes also write `deterministic-review.md`.
The chair checks evidence and combined impact; candidate severity is not an
unreviewable verdict. It records why candidates are rejected/downgraded and emits
exactly one final `VERDICT: PASS` or `VERDICT: FAIL` line with a substantive body.
PASS is permitted only after all blocking candidates and material uncertainty
are resolved. A deterministic FAIL report is not the deterministic PASS mode.
Result `failure_codes` and summary `failures` serve different scopes. Keep raw
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
