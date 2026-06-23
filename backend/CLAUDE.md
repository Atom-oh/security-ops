# backend/ — AgentCore container

The Bedrock AgentCore Runtime container: the 8-phase scanning pipeline + the invocation router.

## Layout
- `app.py` — `BedrockAgentCoreApp` entrypoint + pure `route(payload, context, deps)` (unit-tested). Actions: `scan`, `scan_async`, `list_history`, `get_scan`, `OPTIONS`/CORS, and admin-only `prompt_list`/`prompt_get`/`prompt_create`/`prompt_preview`/`prompt_activate` (ADR-001, gated by `cognito:groups`). Identity (and admin role) from the verified bearer JWT (`sub`/`cognito:groups`). Scans resolve+pin the active prompt set inline at creation; `scan_worker` hash-verifies the inline bodies and never reads the store.
- `pipeline/prompts_store.py` — ADR-001 versioned prompt store (`PromptStore` + `InMemoryPromptStore`): immutable `V#` versions, CAS `ACTIVE` pointer, `AUDIT#` events, `resolve_active_set` (fail-closed on outage), `validate_prompt_body` (defense-in-depth) + canonical `prompt_hash` (SHA-256). Reuses the `SCAN_HISTORY` table (`PK=PROMPT#<agentKey>`).
- `pipeline/` — `orchestrator.py` wires phases 0→7; `config.py` (ScanConfig, Finding, enums, `enforce_budget`); `phase0_languages`, `phase1_slicing`, `risk_score`, `phase2_ranker`, `phase25_prefilter` (secrets/CWE-798), `phase3_hunter` (pass@k), `phase35_challenger`, `phase4_validator`, `ensemble` (Phase 4.5 cross-family), `phase6_report` (ASFF + gate), `phase7_fpmemory`.
- `agents/` — `models.py` (region→profile, thinking fields), `bedrock.py` (Converse wrapper + JSON extract), `openai_mantle.py` (GPT-5.x via bedrock-mantle SigV4), `prompts.py` (defensive, nonce-wrapped; `PromptSet`/`CODE_SAFETY_PREAMBLE`/`system_for` for the ADR-001 editable system prompts — the preamble + scaffolding are never editable).
- `tools/` — `history.py` (DynamoDB), `sandbox.py` (Code Interpreter), `staleness.py`.
- `sample-target/` — intentionally-vulnerable 8-CWE corpus (test target only — never deploy).

## Rules
- Python 3.9-compatible. Tests mock Bedrock/AWS (moto for DynamoDB) — never hit the network.
- New external deps are injected into `FSIMythosPipeline`/`Deps`, not imported at call sites.
- Per-file phase errors are isolated; total Hunter failure raises (no false "clean").

## Commands
```bash
cd backend && pytest          # unit tests
docker build --platform linux/arm64 -t fsi-mythos .   # container (ARM64)
```
