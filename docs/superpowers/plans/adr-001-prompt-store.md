# Plan — ADR-001: Versioned Prompt Store + Admin Editing UI

Implements ADR-001. Externalizes the four editable agent **system** prompts (ranker, hunter,
challenger, validator) to a DynamoDB-backed immutable versioned store, with an admin editing UI,
resolved+pinned at scan-creation time. TDD; each task is one local commit.

## Security mandates (must hold every task)
- **Injection scaffolding stays in code**: `build_untrusted_block`, `untrusted_preamble`, delimiter
  defanging, and the nonce-wrapping user-prompt builders remain in `backend/agents/prompts.py`.
  Editable surface = the 4 **system** strings only. The store cannot disable the guard.
- **agentKey allowlist** server-side: only `ranker|hunter|challenger|validator`.
- **Prompt body is itself an injection vector** → `validate_prompt_body` (length cap + banned
  patterns) on every create; activation requires a passed validation/preview.
- **RBAC server-side** from the verified JWT `cognito:groups` (admin group); audit `author` = verified
  `sub`, never payload.
- **Immutable versions, CAS activation**; **no TTL** on `PROMPT#*` items; SK zero-padded width 6.
- **Pinned at scan creation**: scan record + worker message carry version id **and** prompt hash;
  worker resolves bodies by the **pinned** version, not the live active pointer.
- **IAM read/write split**: scan/worker path cannot write `PROMPT#*` items.

## Design decisions
- Reuse the existing `SCAN_HISTORY` table (single-table). Prompt items: `PK=PROMPT#<agentKey>`,
  `SK=V#<000001>` (immutable version: body, author, createdAt, note, hash) | `SK=ACTIVE`
  (activeVersion, updatedBy, updatedAt). Coexists with scan-history items.
- DI mirrors `ScanHistory`/`InMemoryFPStore`: `PromptStore(table, resource=)` + `InMemoryPromptStore`
  fake for unit tests.
- Full live-benchmark dry-run is an **injected** seam (`benchmark_runner`) so tests use a fake; the
  deterministic validate+scaffolding-render preview is the always-on hard gate before activate.

## Files (scope)
- backend/pipeline/prompts_store.py
- backend/agents/prompts.py
- backend/pipeline/config.py
- backend/pipeline/phase2_ranker.py
- backend/pipeline/phase3_hunter.py
- backend/pipeline/phase35_challenger.py
- backend/pipeline/phase4_validator.py
- backend/pipeline/ensemble.py
- backend/app.py
- backend/tests/test_prompts_store.py
- backend/tests/test_prompts_wiring.py
- backend/tests/test_app_prompts.py
- infra/modules/data/main.tf
- infra/modules/agentcore/main.tf
- frontend/src/auth/cognito.ts
- frontend/src/api/agentcore.ts
- frontend/src/api/types.ts
- frontend/src/pages/PromptAdminPage.tsx
- frontend/src/components/Sidebar.tsx
- frontend/src/App.tsx
- CLAUDE.md
- backend/CLAUDE.md
- docs/architecture.md
- CHANGELOG.md
- docs/decisions/ADR-001-prompt-store-and-editing-ui.md

## Tasks

### Backend — store core
- [ ] T1: `validate_prompt_body(body)` + `AGENT_KEYS` allowlist in `backend/pipeline/prompts_store.py`.
  Tests (`test_prompts_store.py`): valid body passes; >20 KB rejected; banned patterns rejected
  (`ignore previous`, `disregard (all )?(previous|above)`, `system:`/role-override markers, an attempt
  to emit/close an untrusted-nonce delimiter); unknown agentKey rejected. Commit.
- [ ] T2: `PromptStore` + `InMemoryPromptStore` create/get/list versions — immutable items, SK
  `V#` zero-padded 6, fields body/author/createdAt/note/hash; no TTL attribute written. Tests:
  create returns v1 then v2 (append-only, never mutates v1); list ordered; unknown key raises. Commit.
- [ ] T3: `activate(agent_key, version, updated_by, expected_prev)` CAS conditional write + `get_active`.
  Tests: first activate ok; stale `expected_prev` rejected (lost-update prevented); activate a
  nonexistent version rejected. Commit.
- [ ] T4: `resolve_active_set()` → `{agent: {version, body, hash}}` with **code-default fallback** when
  the store is empty/unreachable. Tests: empty store → all defaults with `version="default"`; with an
  active version → that body+id+hash; store error → defaults (never raises). Commit.

### Backend — wiring
- [ ] T5: `PromptSet` dataclass (4 system strings) + `DEFAULT_PROMPT_SET` built from existing constants in
  `backend/agents/prompts.py` (scaffolding/user-builders untouched). Test: `DEFAULT_PROMPT_SET` fields
  equal the current `*_SYSTEM` constants. Commit.
- [ ] T6: `ScanConfig` gains `prompts: Optional[PromptSet]=None`, `pinned_prompt_versions: Dict[str,str]`,
  `prompt_hashes: Dict[str,str]` in `backend/pipeline/config.py`. Test: defaults preserve current behavior.
  Commit.
- [ ] T7: phases use `config.prompts.<agent>` system when present else the code constant —
  `phase2_ranker.py`, `phase3_hunter.py`, `phase35_challenger.py`, `phase4_validator.py`, `ensemble.py`.
  Tests (`test_prompts_wiring.py`, capture-converse pattern): a custom `PromptSet` system string reaches
  the model; with `prompts=None` the default constant is used unchanged. Commit.

### Backend — app routes + pinning
- [ ] T8: Pin at scan creation in `backend/app.py` — `Deps.prompt_store`; on `scan`/`scan_async` resolve
  `resolve_active_set()`, record `promptVersions`+`promptHashes` on the scan record and worker message;
  `_build_config` accepts the resolved `PromptSet`; `scan_worker` rebuilds the `PromptSet` from the
  **pinned** version ids (fallback default), never the live active pointer. Tests (`test_app_prompts.py`):
  scan record carries pinned versions; changing the active pointer after enqueue does not change the
  worker's resolved prompts. Commit.
- [ ] T9: `_is_admin(context)` from verified `cognito:groups`; routes `prompt_list`/`prompt_get`/
  `prompt_create`/`prompt_activate`; non-admin → 403; `author` taken from verified `sub`, not payload;
  agentKey allowlist enforced. Tests: non-admin blocked on every write route; admin allowed; author is
  the JWT sub even if payload lies. Commit.
- [ ] T10: `prompt_preview` (deterministic: `validate_prompt_body` + render the fully nonce-scaffolded
  prompt, **no model call**) returns a preview/validation token; `prompt_activate` rejects a version that
  has not passed validation; optional injected `benchmark_runner` seam recorded but not required green in
  unit tests. Tests: activate-without-validation rejected; preview blocks banned content; scaffolding is
  present in the rendered preview. Commit.

### Infra
- [ ] T11: IAM read/write split — in `infra/modules/agentcore/main.tf` scope the scan/worker role's
  DynamoDB write actions (`PutItem`/`UpdateItem`/`DeleteItem`) with a `dynamodb:LeadingKeys` condition that
  **excludes** `PROMPT#*` (worker may read prompts, not write them); admin write path keeps write on
  `PROMPT#*`. Add a comment in `infra/modules/data/main.tf` documenting prompt items reuse the table and
  must not get a TTL. `cd infra/envs/seoul && terraform init -backend=false && terraform validate`. Commit.

### Frontend
- [ ] T12: `groupsFrom(session)`/`isAdmin(session)` from the id-token `cognito:groups` in
  `frontend/src/auth/cognito.ts`; prompt admin calls in `frontend/src/api/agentcore.ts` + types in
  `frontend/src/api/types.ts` (listPrompts, getPromptVersions, createPromptVersion, previewPrompt,
  activatePromptVersion). `npm run build`. Commit.
- [ ] T13: `frontend/src/pages/PromptAdminPage.tsx` (per-agent version list, view/diff, edit→create new
  version, preview, activate/rollback) using the existing CSS-variable design system; admin-only nav item
  in `frontend/src/components/Sidebar.tsx`; route guard in `frontend/src/App.tsx` (render only when
  `isAdmin`). `npm run build`. Commit.

### Docs
- [ ] T14: Sync `CLAUDE.md` (root) + `backend/CLAUDE.md` + `docs/architecture.md` + `CHANGELOG.md` with the
  prompt store; add an "Implementation" note to `docs/decisions/ADR-001-prompt-store-and-editing-ui.md`.
  Commit.
