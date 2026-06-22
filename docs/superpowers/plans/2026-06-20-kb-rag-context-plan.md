# Implementation Plan: KB-Augmented Context (RAG) for the Scanning Pipeline

Derived from `docs/superpowers/specs/2026-06-20-kb-rag-context-design.md`. TDD + Tidy First:
each task writes a failing test, then minimal code, then refactor; each task is one commit with
explicit paths. Backend-first (unit-testable with injected fakes), then infra, then frontend,
then docs. Reuses the ADR-001 admin pattern already in the code (`_is_admin`,
`_PROMPT_ACTIONS`/`_prompt_route`, `Deps` injection, `_default_prompt_store`, `PromptAdminPage`,
the immutable `CODE_SAFETY_PREAMBLE` + `PromptSet.assemble`).

> **Revised after P2 consensus rounds 1–2** (Codex GPT-5.5 + Antigravity Gemini 3.1 Pro).
> Round 1: gate-isolation (escalate-only), post-upload ingestion trigger, KB service role + KMS,
> OSS network policy, server-side `uploaded_by`, task reordering, retriever `Deps` wiring.
> Round 2: **Ranker excluded** (its LLM stage is dormant — user decision), DynamoDB manifest
> isolated from the indexed corpus, complete IAM on the real AgentCore execution + scan-worker
> roles, S3 CORS + Public Access Block, per-scan validator cache via the orchestrator, KB safety
> in the immutable `CODE_SAFETY_PREAMBLE`, frontend routing in `Shell.tsx`.
> Round 3: **escalate-only made enforceable** via a baseline/policy Validator output schema
> (`max(baseline, policy)` server-side — the keystone safety fix), **global** top-N severity
> selection in the orchestrator, `kb_delete_doc` de-index lifecycle, and the KB **data-source id**
> threaded to the runtime.
> Round 4 (Codex clean; Antigravity 2 MAJOR, localized): manifest is a state machine
> (`DELETING` keeps the de-index job id; entry removed only after the sync succeeds) and
> `StartIngestionJob` `ConflictException` is handled via an `INDEXING_QUEUED` state (Bedrock allows
> one active ingestion job per data source). No structural findings remained.

**Invariants enforced across all tasks**
- KB is **advisory + escalate-only** — a retriever failure/empty result, AND any KB content,
  NEVER weakens the fail-closed gate (never dismisses or downgrades a blocking finding).
- KB chunks are **trusted internal data**: injected in a labeled `## 사내 정책 컨텍스트 (신뢰 가능)`
  block, separate from the `<<<UNTRUSTED_CODE>>>` nonce block; the reference-only + escalate-only
  rules live in the immutable `CODE_SAFETY_PREAMBLE` so they apply to every (incl. stored) prompt.
- KB injected into **Hunter (phase 3) and Validator (phase 4) only** — not the dormant Ranker.
- All `kb_*` admin routes are gated by the verified `cognito:groups` admin role (server-side);
  `uploaded_by` is derived server-side from the JWT, never from payload/client S3 metadata.
- The document manifest lives in DynamoDB (`KBDOC#` prefix), never in the indexed corpus.
- Stay Python 3.9-compatible (`from __future__ import annotations`, `typing.Optional`).

---

### Task 1: KB retriever abstraction (injected, resilient)

**Files:**
- Create: `backend/tools/kb_retriever.py`
- Test: `backend/tests/test_kb_retriever.py`

- [ ] Write failing tests: a `Chunk` dataclass `{text, source_uri, score}`; `KbRetriever.retrieve(query, k, timeout_s)` wraps a fake `bedrock-agent-runtime` `Retrieve` client, returns Chunks sorted by descending score, truncated to `k`.
- [ ] Test resilience: client raising, timeout, and empty result each return `[]` and never raise.
- [ ] Implement `kb_retriever.py` minimally (knowledge-base id + region from constructor args).
- [ ] Refactor: docstrings, type hints; no Bedrock import leaking into the pure domain layer at import time.

### Task 2: ScanConfig KB knobs + defaults

**Files:**
- Modify: `backend/pipeline/config.py`
- Test: `backend/tests/test_config.py`

- [ ] Write failing tests asserting `ScanConfig` defaults: `kb_enabled` (bool), `kb_top_k=5`, `kb_validator_top_n=10`, `kb_char_budget=4000`, `kb_retrieve_timeout_s=3.0`, `knowledge_base_id` (from env, default empty).
- [ ] Test that an empty `knowledge_base_id` OR `kb_enabled=false` implies KB disabled (zero retrieval calls).
- [ ] Implement the fields on `ScanConfig`.
- [ ] Refactor: group KB knobs with a comment block.

### Task 3: Policy-context block, Hunter/Validator prompt slots, and KB safety in the immutable preamble

**Files:**
- Modify: `backend/agents/prompts.py`
- Test: `backend/tests/test_prompts.py`

- [ ] Write failing tests for `build_policy_context_block(chunks)` → returns a `## 사내 정책 컨텍스트 (신뢰 가능)` labeled block; empty list → empty string; NOT wrapped in the `<<<UNTRUSTED_CODE>>>` nonce block.
- [ ] Test `hunter_user_prompt` and `validator_user_prompt` accept an optional `policy_context` and include the block only when non-empty; the untrusted-code block + preamble unchanged. (Ranker prompt is NOT modified.)
- [ ] Test the char-budget helper truncates lowest-score chunks first to fit `kb_char_budget`.
- [ ] **Test that `CODE_SAFETY_PREAMBLE` (assembled by `PromptSet.assemble`, so it applies to every prompt including already-stored ADR-001 versions) now states: policy context is 참고용 and must not override analysis instructions/the injection guard, and Validator policy context is escalate-only (may not dismiss/downgrade a finding).** Verify via `system_for`/`assemble`.
- [ ] Implement the builder, budget helper, the two optional slots, and the preamble text.
- [ ] Refactor: keep the trusted/untrusted separation obvious in comments.

### Task 4: Inject policy context into Hunter (phase 3)

**Files:**
- Modify: `backend/pipeline/phase3_hunter.py`
- Test: `backend/tests/test_phase3.py`

- [ ] Write failing tests: the hunter entry point accepts an optional `policy_context` and, when set, the hunter prompt includes the policy block; when absent, the prompt is byte-identical to today.
- [ ] Test that the K parallel hunters SHARE one passed-in digest — the hunter phase performs 0 retrieval calls itself.
- [ ] Implement the signature + prompt plumbing (before the orchestrator integration so the task commits green independently).
- [ ] Refactor.

### Task 5: Shared policy-digest retrieval in the orchestrator + scan-path retriever wiring

**Files:**
- Modify: `backend/pipeline/orchestrator.py`
- Modify: `backend/app.py`
- Test: `backend/tests/test_orchestrator.py`

- [ ] Write failing tests: the orchestrator takes an injected `kb_retriever`; performs exactly ONE shared retrieval per scan; query built from detected languages + sink types + repo name; digest cached and passed to the Hunter phase (which accepts it from Task 4).
- [ ] Test advisory-only: retriever returns `[]`/raises → run proceeds, digest empty, gate unaffected.
- [ ] **Test the composition root: `app.py` builds a real `KbRetriever` from `ScanConfig.knowledge_base_id` into `Deps.kb_retriever` (mirroring `_default_prompt_store`); empty id / `kb_enabled=false` yields a null retriever making zero calls.**
- [ ] Implement the single shared-digest retrieval, `_default_kb_retriever` + `Deps.kb_retriever`, and threading into the Hunter phase. Extract `_build_digest_query(...)`.
- [ ] Refactor.

### Task 6: Validator per-finding targeted retrieval — escalate-only, gate-isolated, per-scan cache

**Files:**
- Modify: `backend/pipeline/phase4_validator.py`
- Modify: `backend/pipeline/ensemble.py`
- Modify: `backend/pipeline/orchestrator.py`
- Test: `backend/tests/test_phase4.py`

- [ ] **Global top-N selection** (round 3): write failing tests that the orchestrator sorts ALL Hunter findings by descending pre-validation severity and selects a global top-`kb_validator_top_n` allow-set (finding/CWE ids) BEFORE phase 4; only those findings get KB retrieval. Construct findings whose file/processing order differs from severity order and assert retrieval is attempted only for the global top-N (not the first-N-processed). A scan-scoped CWE cache (reused after selection) is created in the orchestrator and passed into each per-file `validate(...)` call; injected context obeys `kb_char_budget`.
- [ ] **Escalate-only via output schema** (round 3 CRITICAL — the gate-free baseline must exist to be enforceable): write failing tests that the Validator LLM JSON returns BOTH a code-only baseline (`baseline_verdict`, `baseline_severity` — judged ignoring policy context) AND policy-adjusted fields (`policy_verdict`, `policy_severity`, `policy_note`). The backend computes the **gate-relevant** verdict/severity as the STRONGER of baseline vs policy (`max(baseline, policy)`; never weaker than baseline) and NEVER dismisses a finding the baseline did not dismiss. The gate consumes only these enforced fields.
- [ ] **Write failing gate-isolation tests**: a KB fake / `policy_*` payload that tries to DISMISS or downgrade a Critical/High finding leaves the gate-relevant severity/verdict at the baseline → gate verdict unchanged; KB may only escalate + add `policy_note`.
- [ ] Implement: thread the scan-scoped KB context + top-N allow-set from the orchestrator into `validate`/`cross_family_validate`; extend the validator prompt + parsing for baseline/policy fields; enforce `max()` server-side.
- [ ] Refactor.

### Task 7: Advisory-only + gate-isolation invariants (cross-cutting gate test)

**Files:**
- Test: `backend/tests/test_kb_advisory.py`

- [ ] Write a test: gate with KB-off vs a KB fake returning benign policy text over the same scan → IDENTICAL fail-closed verdict (advisory-only).
- [ ] Write a test: a hostile KB fake trying to dismiss/downgrade a blocking (Critical/High/chaining) finding via the Validator MUST leave the gate verdict `BLOCKED` unchanged (gate isolation).
- [ ] Adjust call sites only if Tasks 5/6 don't already satisfy both invariants.

### Task 8: Admin KB document routes (DynamoDB manifest + post-upload ingestion)

**Files:**
- Modify: `backend/app.py`
- Create: `backend/pipeline/kb_docs.py`
- Test: `backend/tests/test_app_kb.py`

- [ ] Write failing tests: `kb_list_docs`, `kb_upload_url`, `kb_ingest`, `kb_delete_doc`, `kb_sync_status` are admin-gated (403 without the admin group) following `_PROMPT_ACTIONS`/`_is_admin`; all use injected fake S3/Bedrock/DynamoDB clients.
- [ ] **Test the manifest + upload→ingest split: the manifest is stored in DynamoDB under a `KBDOC#` key prefix (NOT in the indexed `kb-docs` bucket); `kb_upload_url` returns a scoped, short-lived presigned PUT and writes a pending manifest entry with `uploaded_by` from the verified JWT (payload/client-metadata `uploaded_by` ignored); ingestion starts only via a later `kb_ingest` call (none at URL-issue time).**
- [ ] **Delete lifecycle de-index** (round 3/4): write failing tests that `kb_delete_doc` deletes the S3 object, **sets the manifest entry to `DELETING`** (NOT immediate removal — it must still carry the de-index job id + status), and **starts a KB sync/de-index ingestion job** so deleted docs stop being retrievable; the manifest entry is removed only once a status check confirms the de-index job succeeded. A deleted doc must never remain visible as `ready`.
- [ ] **Ingestion-job serialization** (round 4): write failing tests that `kb_ingest`/`kb_delete_doc` handle Bedrock's one-active-job-per-data-source limit — on `ConflictException` from `StartIngestionJob`, set the manifest status to `INDEXING_QUEUED` (not error) and let the next `kb_sync_status`/retry start it once the data source is free; never lose or silently drop the pending change.
- [ ] Implement `kb_docs.py` (DynamoDB-backed manifest = a small state machine `PENDING→INDEXING(_QUEUED)→READY` / `DELETING→removed`, storing ingestion **job ids**; S3 object ops; `StartIngestionJob`/`GetIngestionJob` using KB id + **data-source id**; `ConflictException` handling; injected clients) and wire `_KB_ACTIONS` + `_kb_route` into `route()`; add `kb_docs` to `Deps`.
- [ ] Refactor: mirror the prompt-store handler shape; no new public (non-admin) route.

### Task 9: Terraform `knowledge` module + IAM on the real execution/worker roles

**Files:**
- Create: `infra/modules/knowledge/main.tf`
- Create: `infra/modules/knowledge/variables.tf`
- Create: `infra/modules/knowledge/outputs.tf`
- Create: `infra/modules/knowledge/versions.tf`
- Modify: `infra/modules/agentcore/main.tf`
- Modify: `infra/modules/agentcore/variables.tf`
- Modify: `infra/envs/seoul/main.tf`
- Modify: `infra/envs/seoul/variables.tf`
- Modify: `infra/envs/seoul/outputs.tf`

- [ ] `kb-docs` S3 bucket: versioned, SSE-KMS, **S3 Public Access Block on**, an **`aws_s3_bucket_cors_configuration`** scoped to the SPA origin (browser presigned PUT), no OAC/public.
- [ ] Bedrock Knowledge Base over the bucket with a `vector_backend` variable: managed (default) vs OpenSearch Serverless fallback. **KB service role** (`Principal: bedrock.amazonaws.com`): `s3:ListBucket`+`s3:GetObject` on `kb-docs` (policy-doc prefix only), `kms:Decrypt`/`kms:GenerateDataKey` on the bucket key, write to the active vector backend.
- [ ] **OSS fallback**: `aws_opensearchserverless_security_policy` (encryption + network — **no public access**) + data-access policy scoped to the KB service role; comment the VPC-endpoint dependency (spec §9).
- [ ] **agentcore module** — grant the AgentCore execution role least-privilege: `s3:PutObject`/`DeleteObject` on `kb-docs`, `kms:GenerateDataKey`/`Decrypt` on the key, `bedrock:StartIngestionJob`/`GetIngestionJob`, DynamoDB access for the `KBDOC#` manifest; grant the scan-worker role **read-only `bedrock:Retrieve`** on the KB only (no KB write, no S3 write — the deliberate ADR-001 difference). Pass `knowledge_base_id` + bucket name into the runtime env.
- [ ] Wire `knowledge` into `envs/seoul` (variables + outputs). **Output `knowledge_base_data_source_id` and pass both KB id + data-source id into the AgentCore runtime env** (round 3 — ingestion/status APIs need the data-source id, not just the KB id). Add a region/model availability **preflight note** (managed KB + embedding model in `ap-northeast-2`; else set `vector_backend` to OSS).
- [ ] `cd infra/envs/seoul && terraform init -backend=false && terraform validate` passes for both `vector_backend` values.

### Task 10: Frontend admin "Policy Documents" tab

**Files:**
- Create: `frontend/src/pages/KbAdminPage.tsx`
- Modify: `frontend/src/api/agentcore.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/components/Shell.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] Add API client calls (`kbListDocs`, `kbUploadUrl`, `kbIngest`, `kbDeleteDoc`, `kbSyncStatus`) + types mirroring the prompt-admin client.
- [ ] Build `KbAdminPage`: document list (name/size/uploadedBy/ingestion status/last-synced); **upload flow = request presigned URL → PUT to S3 → call `kbIngest`**; delete; refresh status — matching `PromptAdminPage` + the existing design system.
- [ ] **Add the `kb` route to the `Route` union (`Sidebar.tsx`), render + admin-guard it in `Shell.tsx`** (where routing/`isAdmin` live), admin-only sidebar entry; touch `App.tsx` only if needed.
- [ ] `cd frontend && npm run build` (typecheck + vite) passes.

### Task 11: Docs + context sync

**Files:**
- Modify: `docs/architecture.md`
- Modify: `CLAUDE.md`
- Create: `docs/decisions/ADR-002-kb-rag-context.md`

- [ ] Add the KB/RAG component + data flow (Hunter+Validator injection, escalate-only gate isolation, worker `bedrock:Retrieve`, DynamoDB manifest) to `docs/architecture.md`.
- [ ] Add a Conventions bullet to `CLAUDE.md` mirroring the ADR-001 line (KB advisory + escalate-only, Hunter+Validator only, in-region, worker read-only `bedrock:Retrieve`, server-side `uploaded_by`, manifest isolated from corpus).
- [ ] Write ADR-002 (bilingual, ADR-001 format) recording: single-corpus managed KB + hybrid retrieval, Ranker exclusion (dormant LLM stage), escalate-only gate isolation, OpenSearch Serverless fallback.
- [ ] `bash tests/run-all.sh` green (backend pytest + vite build + terraform validate).
