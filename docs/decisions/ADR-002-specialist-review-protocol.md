# ADR-002: Specialist review protocol

## Status and context

Accepted, 2026-09-13, as a design decision. Implementation and activation are
separate reviewed changes; this policy installs neither. The legacy matrix in
`run-panel.sh`, chair in `synthesize.sh`, helpers in `lib.sh` and
`.github/workflows/pr-review.yml` remain active with their existing coverage floor.
Repeated model/lens reviews motivate distinct specialist responsibilities while
retaining independent evidence and the project's defensive, fail-closed contract.

## Decision

Use the fleet schema-1 tags and explicit model bindings in the
[module contract](../../scripts/pr-review/README.md): Astra for Codex correctness,
Opus for Kiro AWS, Sol for Kiro operations and Fable for Claude requirements.
`kiro-fable` is a shared protocol identifier, not the legacy tag or model brand.
The legacy `gpt-5.6-terra:kiro-gpt` slot is replaced only at activation. Kiro aliases
and Codex Runtime/Mantle IDs are distinct; application inference models and
provider configuration are unchanged, and failed selection never permits fallback.

Require complete immutable-scope reports from every required role and independent
OpenAI/Anthropic primary coverage. Only reviewed BASE routing can deactivate an
irrelevant role. Random nonce boundaries and invocation digests bind supplied
input and responses, not model honesty. A deterministic summary is allowed only
with valid coverage and no blocking candidate or uncertainty; otherwise a chair
adjudicates findings and cannot waive coverage failure.

Retain the existing reviewed input-policy exclusions. Exclusions-only opt-in
(`--allow-exclusions-only --policy FILE`) requires the trusted BASE collector to
account for all original paths, bind policy bytes and match every excluded path.
The filtered review input is empty; the report lists exclusions and claims no
model review. Unknown/source omissions or collector failures remain blocking.

Accept an explicit compatibility interface for collector-approved metadata-only
deletions (`path_only` plus `--allow-metadata-only`). The collector must establish
BASE-policy eligibility; deletion headers are validated and withheld bodies are
disclosed. This is not authorization to omit arbitrary source. The generic Git
collector does not use this mode. These two opt-ins have separate evidence rules
in the module contract; a caller-provided hash alone authorizes neither.

## Consequences and verification

Preserve provider bindings, secret/state custody, limits and budgets. New protocol
documentation is English; automated output switches only at activation, leaving
the legacy Korean/English prompts unchanged. No Korean duplicate is required.

The implementation must test scope completeness, exception rules, nonce/receipt
binding, terminal failures, scrubbing and output ownership. Activation must review
the executors, private artifact lifecycle, configured model access and exact-HEAD
publication, and identify the legacy rules it replaces. Configuration and offline
tests are not proof of live availability or deployment.
