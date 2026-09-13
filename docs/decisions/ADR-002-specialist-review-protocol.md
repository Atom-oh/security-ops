# ADR-002: Specialist review protocol

## Status and context

Accepted, 2026-09-13. Policy and protocol/executor installation landed separately.
This activation selects `ROLE_REVIEW=1` in the operational workflow. It replaces
the repeated legacy matrix and dropout floor with complete required-role coverage,
and replaces unconditional synthesis with conditional adjudication. Existing
provider bindings, custody, context, budgets and publication safeguards remain.
The application's defensive scanner and its chaining gate are outside this decision.

## Decision

Use the fleet schema-1 tags in the
[module contract](../../scripts/pr-review/README.md). Its table is the sole
normative mapping of tag, requested model/provider and responsibility.
`kiro-fable` is a compatibility tag for Opus; the Fable model belongs to
`claude-self`.
On the active path, legacy `kiro-opus` maps to specialist `kiro-fable` (same Opus model),
and legacy `kiro-gpt` maps to `kiro-sol` (Terra → Sol). The two specialist Kiro roles
replace the two legacy Kiro rows; they do not run alongside duplicate Opus rows.
Legacy entrypoints remain for regression fixtures. The final specialist tag set
is `codex`, `kiro-fable`, `kiro-sol`, `claude-self`, as listed in the module contract.
Kiro aliases and Bedrock Runtime/Mantle IDs are distinct; application inference models and
provider configuration are unchanged. Required specialist selection failures cannot
be hidden by fallback; the chair retains its explicit primary/fallback configuration.

Require complete immutable-scope reports from every required role and independent
OpenAI/Anthropic primary coverage. Every active role receives the same entire
filtered change; per-role slicing is prohibited. Only reviewed BASE routing may
deactivate Kiro for clearly frontend-only, signal-free changes under criteria
implemented in the reviewed library; unknown or sensitive
paths keep both Kiro roles.
Random nonce boundaries and invocation digests bind supplied
input and responses, not model honesty. A deterministic PASS summary requires valid coverage and no blocking candidate
or uncertainty. Missing/invalid coverage produces a deterministic FAIL report
without a chair. Substantive candidates go to the chair for evidence-based
adjudication: any confirmed CRITICAL/MAJOR issue or unresolved material uncertainty
requires FAIL. Rejected or downgraded candidates need a recorded rationale;
coverage failures cannot be waived.
Model responses remain untrusted through adjudication and publication. The module
contract defines their evidence framing, escaping, scrubbing and final-verdict
validation; neither quoted commands nor model-supplied verdict text is authority.

Primary reviews include cross-file interactions and the combined impact of the
complete change. A potentially blocking chain must be reported as CRITICAL/MAJOR
or unresolved uncertainty, not split into apparently harmless labels. Minor/Info
means the primary reviewers found no blocking standalone or combined impact.
Skipping the chair in that case deliberately replaces the PR pipeline's legacy
always-chair rule. The accepted risk is an interaction missed or misclassified
by both full-change primaries; no cross-report chair adjudication then occurs.
This is not proof that findings cannot combine, and no finding-count heuristic
is approved as a substitute for severity and uncertainty.
The application's vulnerability-scanning pipeline and its chaining gate are
separate and unchanged by this PR-review decision.

Retain the existing reviewed input-policy exclusions. Exclusions-only opt-in
(`--allow-exclusions-only --policy FILE`) requires the trusted BASE collector to
account for all original paths, bind policy bytes and match every excluded path.
The filtered review input is empty; the report lists exclusions and claims no
model review. Unknown/source omissions or collector failures remain blocking.

Retain only the workflow's four lockfile basenames and `reference-docs/` exclusion;
broader rules require a separate BASE-policy decision. These exclusions are an
accepted coverage limitation and must remain visible in the report.

Defer metadata-only deletion support: nonempty `path_only` is rejected in this
rollout. A deletion header, opt-in flag or caller-provided hash cannot authorize
omitting a source body. Future support requires a separately reviewed collector,
BASE-policy eligibility and verification contract.

## Consequences and verification

Preserve provider bindings, secret/state custody, limits and budgets. Protocol
documentation and active review output are English; retained legacy fixtures
keep their earlier prompts. No Korean duplicate is required.

Offline tests cover scope completeness, exception rules, nonce/receipt
binding, terminal failures, scrubbing and output ownership. Activation preserves
private artifact custody and exact-HEAD publication. Configured model access
requires separate native execution evidence. Configuration and offline
tests are not proof of live availability or deployment.
