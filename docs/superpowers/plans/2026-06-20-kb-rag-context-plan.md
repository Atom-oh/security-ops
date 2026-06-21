# Implementation Plan: KB-Augmented Context (RAG) for the Scanning Pipeline

Derived from `docs/superpowers/specs/2026-06-20-kb-rag-context-design.md`. TDD + Tidy First:
each task writes a failing test, then minimal code, then refactor; each task is one commit with
explicit paths. Backend-first (unit-testable with injected fakes), then infra, then frontend,
then docs. Reuses the ADR-001 admin pattern already in the code (`_is_admin`,
`_groups_from_context`, `_PROMPT_ACTIONS`/`_prompt_route`, `Deps` injection, `PromptAdminPage`).

**Invariants enforced across all tasks**
- KB is **advisory only** — a retriever failure/empty result NEVER changes the fail-closed gate.
- KB chunks are **trusted internal data**: injected in a labeled `## 사내 정책 컨텍스트 (신뢰 가능)`
  block, separate from the `<<<UNTRUSTED_CODE>>>` nonce block, and may never override the system
  prompt or injection guard.
- All `kb_*` admin routes are gated by the verified `cognito:groups` admin role (server-side).
- Stay Python 3.9-compatible (`from __future__ import annotations`, `typing.Optional`).

---

### Task 1: KB retriever abstraction (injected, resilient)

**Files:**
- Create: `backend/tools/kb_retriever.py`
- Test: `backend/tests/test_kb_retriever.py`

- [ ] Write failing tests: a `Chunk` dataclass `{text, source_uri, score}`; `KbRetriever.retrieve(query, k, timeout_s)` wraps a fake `bedrock-agent-runtime` `Retrieve` client, returns Chunks sorted by descending score, truncated to `k`.
- [ ] Test resilience: client raising, timeout, and empty result each return `[]` and never raise.
- [ ] Implement `kb_retriever.py` minimally to pass (knowledge-base id + region from constructor args).
- [ ] Refactor: docstrings, type hints; ensure no Bedrock import at module import time leaks into the pure domain layer.

### Task 2: ScanConfig KB knobs + defaults

**Files:**
- Modify: `backend/pipeline/config.py`
- Test: `backend/tests/test_config.py`

- [ ] Write failing tests asserting `ScanConfig` defaults: `kb_enabled` (bool), `kb_top_k=5`, `kb_validator_top_n=10`, `kb_char_budget=4000`, `kb_retrieve_timeout_s=3.0`, `knowledge_base_id` (from env, default empty).
- [ ] Test that an empty `knowledge_base_id` implies KB disabled at runtime.
- [ ] Implement the fields on `ScanConfig`.
- [ ] Refactor: group KB knobs with a comment block.

### Task 3: Trusted policy-context block + prompt slots

**Files:**
- Modify: `backend/agents/prompts.py`
- Test: `backend/tests/test_prompts.py`

- [ ] Write failing tests for `build_policy_context_block(chunks)` → returns a `## 사내 정책 컨텍스트 (신뢰 가능)` labeled block; empty list → empty string; output is NOT wrapped in the `<<<UNTRUSTED_CODE>>>` nonce block.
- [ ] Test `ranker_user_prompt`, `hunter_user_prompt`, `validator_user_prompt` accept an optional `policy_context` and include the block only when non-empty; the untrusted-code block and preamble remain unchanged.
- [ ] Test the char-budget helper truncates lowest-score chunks first to fit `kb_char_budget`.
- [ ] Implement the builder, the budget helper, and the optional slots.
- [ ] Refactor: keep the trusted/untrusted separation obvious in code comments.

### Task 4: Shared policy-digest retrieval in the orchestrator

**Files:**
- Modify: `backend/pipeline/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

- [ ] Write failing tests: orchestrator takes an injected `kb_retriever`; performs exactly ONE shared retrieval per scan; the query is built from detected languages + sink types + repo name; the digest is cached on the run and passed to Ranker and Hunter.
- [ ] Test advisory-only: when the retriever returns `[]`/raises, the run proceeds and the digest is empty.
- [ ] Implement the single shared-digest retrieval and threading into phases 2 and 3.
- [ ] Refactor: extract a small `_build_digest_query(...)` helper.

### Task 5: Inject digest into Ranker (phase 2) and Hunter (phase 3)

**Files:**
- Modify: `backend/pipeline/phase2_ranker.py`
- Modify: `backend/pipeline/phase3_hunter.py`
- Test: `backend/tests/test_phase2.py`
- Test: `backend/tests/test_phase3.py`

- [ ] Write failing tests: when a digest is provided, the ranker prompt and hunter prompt include the policy block.
- [ ] Test that the K parallel hunters SHARE the cached digest — the retriever is called 0 additional times inside the hunter phase.
- [ ] Implement passing `policy_context` through both phases to the prompt builders.
- [ ] Refactor.

### Task 6: Validator per-finding targeted retrieval (CWE cache + top-N + budget)

**Files:**
- Modify: `backend/pipeline/phase4_validator.py`
- Modify: `backend/pipeline/ensemble.py`
- Test: `backend/tests/test_phase4.py`

- [ ] Write failing tests: Validator retrieves per finding keyed on `title + cwe_id`; repeated `cwe_id` within a scan reuses one retrieval (CWE cache); retrieval is capped at `kb_validator_top_n` findings by descending severity; injected context obeys `kb_char_budget`.
- [ ] Test advisory-only: retriever failure → Validator still produces verdicts and the gate outcome is unchanged.
- [ ] Implement the targeted-retrieval loop with cache + caps in the validator (and shared `ensemble.py` path).
- [ ] Refactor.

### Task 7: Advisory-only invariant (cross-cutting gate test)

**Files:**
- Test: `backend/tests/test_kb_advisory.py`

- [ ] Write a test that runs the gate with KB-on vs KB-failing fakes over the same findings and asserts an IDENTICAL fail-closed gate verdict (KB never flips Critical/High/chaining/coverage outcomes).
- [ ] Implement nothing new if Tasks 4/6 already satisfy it; otherwise adjust call sites so KB is strictly advisory.

### Task 8: Admin KB document routes (S3 + ingestion)

**Files:**
- Modify: `backend/app.py`
- Create: `backend/pipeline/kb_docs.py`
- Test: `backend/tests/test_app_kb.py`

- [ ] Write failing tests: `kb_list_docs`, `kb_upload_url`, `kb_delete_doc`, `kb_sync_status` are admin-gated (403 without the admin group) following the `_PROMPT_ACTIONS`/`_is_admin` pattern; `kb_upload_url` returns a scoped, short-lived presigned PUT; all use injected fake S3/Bedrock clients.
- [ ] Implement `kb_docs.py` (S3-backed doc manager + ingestion-job trigger, injected clients) and wire `_KB_ACTIONS` + `_kb_route` into `route()`; add `kb_docs`/`kb_retriever` to `Deps`.
- [ ] Refactor: mirror the prompt-store handler shape; no new public (non-admin) route.

### Task 9: Terraform `knowledge` module (managed KB + OpenSearch Serverless fallback)

**Files:**
- Create: `infra/modules/knowledge/main.tf`
- Create: `infra/modules/knowledge/variables.tf`
- Create: `infra/modules/knowledge/outputs.tf`
- Create: `infra/modules/knowledge/versions.tf`
- Modify: `infra/envs/seoul/main.tf`
- Modify: `infra/envs/seoul/variables.tf`
- Modify: `infra/envs/seoul/outputs.tf`

- [ ] Add the `kb-docs` S3 bucket (versioned, SSE-KMS, private — no public/OAC), a Bedrock Knowledge Base over it, with a `vector_backend` variable selecting managed (default) vs OpenSearch Serverless fallback.
- [ ] IAM: admin ingestion role (S3 put/delete + `bedrock:StartIngestionJob`); scan-worker role granted read-only `bedrock:Retrieve` on the KB only (no KB write, no S3 write) — the deliberate ADR-001 difference.
- [ ] Wire the module into `envs/seoul` with variables and outputs (knowledge-base id surfaced to the runtime env).
- [ ] `cd infra/envs/seoul && terraform init -backend=false && terraform validate` passes for both `vector_backend` values.

### Task 10: Frontend admin "Policy Documents" tab

**Files:**
- Create: `frontend/src/pages/KbAdminPage.tsx`
- Modify: `frontend/src/api/agentcore.ts`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] Add API client calls (`kbListDocs`, `kbUploadUrl`, `kbDeleteDoc`, `kbSyncStatus`) and types mirroring the prompt-admin client.
- [ ] Build `KbAdminPage`: document list (name/size/uploadedBy/ingestion status/last-synced), upload (presigned PUT then trigger ingestion), delete, refresh status — admin-only, matching `PromptAdminPage` structure and the existing design system.
- [ ] Wire the route + sidebar entry (admin-only visibility).
- [ ] `cd frontend && npm run build` (typecheck + vite) passes.

### Task 11: Docs + context sync

**Files:**
- Modify: `docs/architecture.md`
- Modify: `CLAUDE.md`
- Create: `docs/decisions/ADR-002-kb-rag-context.md`

- [ ] Add the KB/RAG component + data flow to `docs/architecture.md`.
- [ ] Add a Conventions bullet to `CLAUDE.md` mirroring the ADR-001 line (KB advisory-only, in-region, worker has read-only `bedrock:Retrieve`).
- [ ] Write ADR-002 (bilingual, same format as ADR-001) recording the single-corpus managed-KB + hybrid-retrieval decision and the OpenSearch Serverless fallback.
- [ ] `bash tests/run-all.sh` green (backend pytest + vite build + terraform validate).
