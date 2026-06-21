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
- Full live-benchmark dry-run is an **injected** seam so tests use a fake; the deterministic
  validate+scaffolding-render preview is the always-on hard gate before activate.

---

### Task 1: Prompt-body validation + agentKey allowlist

**Files:**
- Create: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] Add `AGENT_KEYS = ("ranker", "hunter", "challenger", "validator")` and `validate_prompt_body(body)`.
- [ ] Write failing tests: valid body passes; >20 KB rejected; banned patterns rejected (`ignore previous`,
      `disregard (all )?(previous|above)`, role-override `system:` markers, an attempt to emit/close an
      untrusted-nonce delimiter); unknown agentKey rejected.
- [ ] Implement minimally; run `cd backend && pytest tests/test_prompts_store.py`; commit.

### Task 2: Immutable versioned PromptStore + in-memory fake

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] Add `PromptStore(table_name, region=None, resource=None)` and `InMemoryPromptStore`: `create_version`,
      `get_version`, `list_versions`. Items immutable, `SK=V#<zero-pad-6>`, fields body/author/createdAt/
      note/hash; never write a TTL attribute.
- [ ] Failing tests: create returns v1 then v2 (append-only, v1 never mutated); `list_versions` ordered;
      unknown agentKey raises; `create_version` calls `validate_prompt_body`.
- [ ] Implement; pytest; commit.

### Task 3: CAS activation + active pointer

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] Add `activate(agent_key, version, updated_by, expected_prev=None)` (conditional/compare-and-swap write)
      and `get_active(agent_key)`.
- [ ] Failing tests: first activate ok; stale `expected_prev` rejected (lost-update prevented); activating a
      nonexistent version rejected.
- [ ] Implement; pytest; commit.

### Task 4: resolve_active_set with code-default fallback

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] Add `resolve_active_set()` → `{agent: {version, body, hash}}`; fall back to code defaults when the
      store is empty/unreachable (never raises).
- [ ] Failing tests: empty store → all defaults with `version="default"`; active set → that body+id+hash;
      store error → defaults.
- [ ] Implement; pytest; commit.

### Task 5: PromptSet dataclass + DEFAULT_PROMPT_SET

**Files:**
- Modify: `backend/agents/prompts.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Add a `PromptSet` dataclass (4 system strings) and `DEFAULT_PROMPT_SET` built from the existing
      `*_SYSTEM` constants. Leave scaffolding/user-prompt builders untouched.
- [ ] Failing test: `DEFAULT_PROMPT_SET` fields equal the current `RANKER_SYSTEM`/`HUNTER_SYSTEM`/
      `CHALLENGER_SYSTEM`/`VALIDATOR_SYSTEM`.
- [ ] Implement; pytest; commit.

### Task 6: ScanConfig carries the resolved+pinned prompt set

**Files:**
- Modify: `backend/pipeline/config.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Add `prompts: Optional[PromptSet]=None`, `pinned_prompt_versions: Dict[str,str]`,
      `prompt_hashes: Dict[str,str]` to `ScanConfig`.
- [ ] Failing test: defaults are empty/None and current behavior is unchanged.
- [ ] Implement; pytest; commit.

### Task 7: Phases read system prompt from config when present

**Files:**
- Modify: `backend/pipeline/phase2_ranker.py`
- Modify: `backend/pipeline/phase3_hunter.py`
- Modify: `backend/pipeline/phase35_challenger.py`
- Modify: `backend/pipeline/phase4_validator.py`
- Modify: `backend/pipeline/ensemble.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Each phase uses `config.prompts.<agent>` system string when present, else the code constant.
- [ ] Failing tests (capture-converse pattern): a custom `PromptSet` system reaches the model; with
      `prompts=None` the default constant is used unchanged.
- [ ] Implement; pytest; commit.

### Task 8: Pin active versions at scan creation; worker uses pinned

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] Add `Deps.prompt_store`. On `scan`/`scan_async` resolve `resolve_active_set()`, record
      `promptVersions`+`promptHashes` on the scan record and the worker message; `_build_config` accepts the
      resolved `PromptSet`; `scan_worker` rebuilds the `PromptSet` from the **pinned** version ids (fallback
      default), never the live active pointer.
- [ ] Failing tests: scan record carries pinned versions; changing the active pointer after enqueue does not
      change the worker's resolved prompts.
- [ ] Implement; pytest; commit.

### Task 9: Admin RBAC + prompt admin routes

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] Add `_is_admin(context)` reading verified `cognito:groups`; routes `prompt_list`/`prompt_get`/
      `prompt_create`/`prompt_activate`; non-admin → 403; `author` from verified `sub` (not payload);
      enforce the agentKey allowlist.
- [ ] Failing tests: non-admin blocked on every write route; admin allowed; author is the JWT sub even when
      the payload supplies a different author.
- [ ] Implement; pytest; commit.

### Task 10: Preview/validate gate before activate

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] Add `prompt_preview` (deterministic: `validate_prompt_body` + render the fully nonce-scaffolded prompt,
      **no model call**) returning a validation token; `prompt_activate` rejects a version that has not passed
      validation. Wire an injected `benchmark_runner` seam (recorded, not required green in unit tests).
- [ ] Failing tests: activate-without-validation rejected; preview blocks banned content; the rendered preview
      contains the nonce scaffolding.
- [ ] Implement; pytest; commit.

### Task 11: IAM read/write split + table note

**Files:**
- Modify: `infra/modules/agentcore/main.tf`
- Modify: `infra/modules/data/main.tf`

- [ ] Scope the scan/worker role's DynamoDB write actions (`PutItem`/`UpdateItem`/`DeleteItem`) with a
      `dynamodb:LeadingKeys` condition that excludes `PROMPT#*` (worker may read, not write prompts); the
      admin write path keeps write on `PROMPT#*`. Document in `data/main.tf` that prompt items reuse the
      table and must not receive a TTL.
- [ ] Run `cd infra/envs/seoul && terraform init -backend=false && terraform validate`; commit.

### Task 12: Frontend admin detection + API client

**Files:**
- Modify: `frontend/src/auth/cognito.ts`
- Modify: `frontend/src/api/agentcore.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] Add `groupsFrom(session)`/`isAdmin(session)` from the id-token `cognito:groups`; add prompt admin API
      calls (listPrompts, getPromptVersions, createPromptVersion, previewPrompt, activatePromptVersion) and
      their types.
- [ ] Run `cd frontend && npm run build`; commit.

### Task 13: Prompt admin page + nav + route guard

**Files:**
- Create: `frontend/src/pages/PromptAdminPage.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] Build `PromptAdminPage` (per-agent version list, view/diff, edit→create version, preview,
      activate/rollback) on the existing CSS-variable design system; admin-only nav item in `Sidebar`;
      `App.tsx` renders the page only when `isAdmin`.
- [ ] Run `cd frontend && npm run build`; commit.

### Task 14: Docs sync

**Files:**
- Modify: `CLAUDE.md`
- Modify: `backend/CLAUDE.md`
- Modify: `docs/architecture.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/decisions/ADR-001-prompt-store-and-editing-ui.md`

- [ ] Sync CLAUDE.md (root + backend), architecture, and CHANGELOG with the prompt store; add an
      "Implementation" note to ADR-001.
- [ ] Commit.
