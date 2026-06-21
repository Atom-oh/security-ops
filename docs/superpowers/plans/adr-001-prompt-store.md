# Plan v2 — ADR-001: Versioned Prompt Store + Admin Editing UI

Implements ADR-001. Externalizes the four editable agent **system** prompts (ranker, hunter,
challenger, validator) to a DynamoDB-backed immutable versioned store, with an admin editing UI,
**resolved + pinned (bodies inline) at scan-creation time**. TDD; each task = one local commit.

> **v2 revision** after the P2 multi-AI gate (codex gpt-5.5, agy Gemini-3.1-Pro, kiro opus/kimi/glm —
> all FAIL, verified against code). Key change: **pin by embedding the resolved prompt bodies inline**
> in the scan record + SQS worker message (not just version ids). The worker never reads `PROMPT#`
> items, so: no silent fallback, hash-verified integrity, and the IAM read/write split is trivial.

## Verified facts (drove the redesign)
- System prompts are passed **verbatim** (`system=[{"text": system}]` in `agents/bedrock.py`) — never
  `.format()`'d, so a stray `{}` does not crash. (Placeholder guard kept as cheap defense-in-depth.)
- There is exactly **one** DynamoDB-writing principal today: the AgentCore `exec` role
  (`infra/modules/agentcore/main.tf`, RW on the single table ARN). **No separate worker role exists.**
- Table key schema: `hash_key=userId` (bare Cognito sub), `range_key=scanId`. Prompt items reuse the
  table with `PK=PROMPT#<agentKey>` — the prefix is in the **partition key**, so `dynamodb:LeadingKeys`
  matches it (an *exclusion* needs an explicit **Deny**, since userId partitions are unbounded UUIDs).

## Security mandates (must hold every task)
- **Injection scaffolding + a safety preamble stay in code.** The resolved system prompt is assembled
  in code as `CODE_SAFETY_PREAMBLE + stored_body` (string concat, never `.format` on the body). The
  nonce-wrapping user-prompt builders, `build_untrusted_block`, `untrusted_preamble` remain in
  `backend/agents/prompts.py`. Editable surface = the 4 system bodies only; the store cannot remove the
  guard or the preamble.
- `validate_prompt_body` is **defense-in-depth, not the injection control** (the editable string is the
  trusted channel). It enforces: ≤20 KB; NFKC-normalize + strip zero-width/control chars before checks;
  reject banned patterns incl. Korean variants (`무시`, `이전 지침`) and nonce-delimiter emission; reject
  unbalanced `{`/`}` placeholders; `note` ≤ 500 chars. agentKey allowlist `ranker|hunter|challenger|validator`.
- **RBAC server-side on every prompt route** (list/get/preview/create/activate) from the verified bearer
  JWT `cognito:groups` (admin group). Bearer is already signature-verified by the AgentCore authorizer;
  backend is authoritative (UI gating is cosmetic). Audit `author` = verified `sub`, never payload.
- **Immutable versions**: create uses a conditional `attribute_not_exists` write + retry (concurrent-create
  safe). **Activate = true CAS** (`UpdateItem` ConditionExpression on `activeVersion`). **No TTL** on
  `PROMPT#*` items. SK zero-padded width 6. Hash = **SHA-256 over the exact UTF-8 body**, defined once.
- **Append-only audit**: `SK=AUDIT#<ts>#<rand>` items on create/activate/rollback; failed-authz logged.
- **Pinned-inline at scan creation**: scan record + worker message carry, per agent, `{version, hash,
  body}`. The worker rebuilds the `PromptSet` from the **inline bodies**, verifies `sha256(body)==hash`,
  and **aborts on mismatch/missing — never falls back**. Resolution at creation distinguishes empty store
  (→ code defaults, `version="default"`, legit) from **unreachable** (→ fail-closed + metric).
- **IAM read/write split**: the inline-body design means the scan **worker needs no `PROMPT#` access at
  all**. The (to-be-provisioned) Fargate worker role gets an explicit **Deny** on
  `PutItem/UpdateItem/DeleteItem/BatchWriteItem` where `dynamodb:LeadingKeys=["PROMPT#*"]`. PROMPT# writes
  stay only on the admin/runtime principal.

## Design decisions
- Reuse the existing `SCAN_HISTORY` table. Items: `PK=PROMPT#<agentKey>`, `SK=V#<000001>` (immutable:
  body, author, createdAt, note, hash, validatedHash?, validatedAt?), `SK=ACTIVE` (activeVersion,
  updatedBy, updatedAt), `SK=AUDIT#<ts>#<rand>` (event, actor, version).
- DI mirrors `ScanHistory`/`InMemoryFPStore`: `PromptStore(table, resource=)` + `InMemoryPromptStore`.
- **Validation state is server-side**, keyed to the exact version+hash (NO client-passed token — avoids
  forgery/replay/TOCTOU). `prompt_preview` validates + renders the scaffolded prompt (no model call) and
  stamps `validatedHash` on the version item; `prompt_activate` requires `validatedHash == version.hash`.
- Live-benchmark dry-run is an **injected** seam; this plan ships the deterministic validate+render gate
  as the blocking precondition and records the benchmark hook (not required green in unit tests).

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
- infra/modules/agentcore/main.tf
- infra/modules/agentcore/variables.tf
- infra/modules/data/main.tf
- infra/envs/seoul/main.tf
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

---

### Task 1: Prompt-body validation + agentKey allowlist + canonical hash

**Files:**
- Create: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] Add `AGENT_KEYS`, `prompt_hash(body)` = `sha256(body.encode("utf-8")).hexdigest()`, and
      `validate_prompt_body(body, note="")`: NFKC-normalize + strip zero-width/control; reject >20 KB,
      banned patterns (`ignore previous`, `disregard (all )?(previous|above)`, role-override `system:`,
      Korean `무시`/`이전 지침`, attempts to emit/close the untrusted-nonce delimiter), unbalanced `{`/`}`,
      `note` >500 chars; reject unknown agentKey.
- [ ] Failing tests for each branch (valid; oversize; each banned pattern incl. Korean; `{` imbalance;
      long note; unknown key); `prompt_hash` is stable SHA-256.
- [ ] Implement; `cd backend && pytest tests/test_prompts_store.py`; commit.

### Task 2: Immutable versioned store (concurrent-create safe)

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] `PromptStore(table_name, region=None, resource=None)` + `InMemoryPromptStore`: `create_version`
      (conditional `attribute_not_exists(SK)` on `V#<n+1>`, retry on conflict; fields body/author/
      createdAt/note/hash; no TTL), `get_version`, `list_versions` (filter `begins_with(SK,"V#")`).
- [ ] Failing tests: v1 then v2 append-only (v1 never mutated); simulated concurrent create does not
      overwrite (second gets n+2); list ordered + excludes ACTIVE; `create_version` calls validation.
- [ ] Implement; pytest; commit.

### Task 3: CAS activation + active pointer + audit events

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] `activate(agent_key, version, updated_by, expected_prev=None)` via `UpdateItem` ConditionExpression
      on `activeVersion` (true CAS); `get_active`; append-only `AUDIT#<ts>#<rand>` item on create/activate.
- [ ] Failing tests: first activate ok; stale `expected_prev` rejected; activate nonexistent version
      rejected; an audit item is written per create+activate.
- [ ] Implement; pytest; commit.

### Task 4: resolve_active_set — empty vs unreachable

**Files:**
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_prompts_store.py`

- [ ] `resolve_active_set()` → `{agent: {version, body, hash}}`: empty store → code defaults
      (`version="default"`, hash of the default body); **unreachable** → raise `PromptStoreUnavailable`
      (caller fail-closes), not a silent default.
- [ ] Failing tests: empty → defaults with default hashes; active set → that body+id+hash; unreachable
      (store raises) → `PromptStoreUnavailable`.
- [ ] Implement; pytest; commit.

### Task 5: PromptSet + code safety preamble + DEFAULT_PROMPT_SET

**Files:**
- Modify: `backend/agents/prompts.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Add `CODE_SAFETY_PREAMBLE` (immutable, in code), a `PromptSet` dataclass (4 resolved system strings)
      with `assemble(agent, stored_body)` = `CODE_SAFETY_PREAMBLE + "\n\n" + stored_body` (concat, no
      `.format`), and `DEFAULT_PROMPT_SET` from the existing `*_SYSTEM` constants. Scaffolding/user
      builders untouched.
- [ ] Failing tests: `DEFAULT_PROMPT_SET` bodies equal current constants; `assemble` always prepends the
      preamble even for an adversarial body.
- [ ] Implement; pytest; commit.

### Task 6: ScanConfig carries the pinned prompt set (inline)

**Files:**
- Modify: `backend/pipeline/config.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Add `prompts: Optional[PromptSet]=None`, `pinned_prompt_versions: Dict[str,str]`,
      `prompt_hashes: Dict[str,str]` to `ScanConfig`.
- [ ] Failing test: defaults None/empty; current behavior unchanged.
- [ ] Implement; pytest; commit.

### Task 7: Phases read system prompt from config; fail-closed guard

**Files:**
- Modify: `backend/pipeline/phase2_ranker.py`
- Modify: `backend/pipeline/phase3_hunter.py`
- Modify: `backend/pipeline/phase35_challenger.py`
- Modify: `backend/pipeline/phase4_validator.py`
- Modify: `backend/pipeline/ensemble.py`
- Test: `backend/tests/test_prompts_wiring.py`

- [ ] Each phase uses `config.prompts.<agent>` when present, else the code constant. **Fail-closed**: if
      `pinned_prompt_versions` is non-empty but `config.prompts` is None, raise (no silent downgrade).
- [ ] Failing tests (capture-converse): a custom `PromptSet` system reaches the model; `prompts=None` +
      no pins → default constant unchanged; pins set + `prompts=None` → raises.
- [ ] Implement; pytest; commit.

### Task 8a: Pin resolved bodies into the scan record + worker message

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] Add `Deps.prompt_store`. On `scan`/`scan_async` call `resolve_active_set()`; on
      `PromptStoreUnavailable` fail-closed (error result + metric/log). Record per-agent `{version, hash}`
      on the scan record and `{version, hash, body}` in the worker message; `_build_config` accepts the
      resolved `PromptSet`.
- [ ] Failing tests: scan record carries pinned versions+hashes; worker message carries inline bodies;
      store-unreachable → fail-closed error (no scan with defaults).
- [ ] Implement; pytest; commit.

### Task 8b: Worker rebuilds from inline bodies + hash verification

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] `scan_worker` rebuilds `PromptSet` from the **inline** message bodies, verifies
      `prompt_hash(body)==pinned hash` per agent, and **aborts** (status=error) on mismatch/missing —
      never reads `PROMPT#` and never falls back. Changing the active pointer after enqueue does not
      affect the running scan.
- [ ] Failing tests: worker uses inline bodies (not live active); tampered body (hash mismatch) → abort;
      post-enqueue activation does not change resolved prompts.
- [ ] Implement; pytest; commit.

### Task 9: Admin RBAC on all prompt routes

**Files:**
- Modify: `backend/app.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] `_is_admin(context)` from verified `cognito:groups`; gate `prompt_list`/`prompt_get`/`prompt_preview`
      /`prompt_create`/`prompt_activate` (read routes admin-only too — prompts are guard IP); non-admin →
      403 + logged; `author` from verified `sub` (not payload); enforce agentKey allowlist.
- [ ] Failing tests: non-admin blocked on every prompt route (incl. read/preview); admin allowed; author
      is JWT sub even when payload supplies a different author.
- [ ] Implement; pytest; commit.

### Task 10: Server-side validate/preview gate before activate

**Files:**
- Modify: `backend/app.py`
- Modify: `backend/pipeline/prompts_store.py`
- Test: `backend/tests/test_app_prompts.py`

- [ ] `prompt_preview`: `validate_prompt_body` + render the fully nonce-scaffolded prompt (no model call);
      on success **stamp `validatedHash` on the version item** (server-side state). `prompt_activate`
      rejects unless `version.validatedHash == version.hash`. Record (don't require green) an injected
      `benchmark_runner` hook.
- [ ] Failing tests: activate without prior preview rejected; editing the body after preview invalidates
      (hash changes) → activate rejected; preview blocks banned content; rendered preview contains the
      nonce scaffolding.
- [ ] Implement; pytest; commit.

### Task 11: IAM — worker role write-Deny on PROMPT#*, table note

**Files:**
- Modify: `infra/modules/agentcore/main.tf`
- Modify: `infra/modules/agentcore/variables.tf`
- Modify: `infra/envs/seoul/main.tf`
- Modify: `infra/modules/data/main.tf`

- [ ] Add a Fargate **scan-worker IAM role** (or a `var.worker_role` seam) with table read + an explicit
      **Deny** on `PutItem/UpdateItem/DeleteItem/BatchWriteItem` where `dynamodb:LeadingKeys=["PROMPT#*"]`
      (worker needs no PROMPT# access given inline bodies; the Deny is belt-and-suspenders). PROMPT# write
      stays on the admin/exec role. Document in `data/main.tf` that PROMPT# items reuse the table and must
      never get a TTL.
- [ ] `cd infra/envs/seoul && terraform init -backend=false && terraform validate`; commit.

### Task 12: Frontend admin detection + API client

**Files:**
- Modify: `frontend/src/auth/cognito.ts`
- Modify: `frontend/src/api/agentcore.ts`
- Modify: `frontend/src/api/types.ts`

- [ ] `groupsFrom(session)`/`isAdmin(session)` from the id-token `cognito:groups` (UI gating only; backend
      authoritative); prompt admin API calls (listPrompts, getPromptVersions, createPromptVersion,
      previewPrompt, activatePromptVersion) + types.
- [ ] `cd frontend && npm run build`; commit.

### Task 13a: Prompt admin page shell — list + view (read-only)

**Files:**
- Create: `frontend/src/pages/PromptAdminPage.tsx`
- Modify: `frontend/src/components/Sidebar.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] `PromptAdminPage` with per-agent version list + read-only view (bodies rendered HTML-escaped in
      `<pre>` — never `dangerouslySetInnerHTML`); admin-only nav item in `Sidebar`; `App.tsx` renders the
      page only when `isAdmin`.
- [ ] `cd frontend && npm run build`; commit.

### Task 13b: Prompt admin edit → preview → activate/rollback

**Files:**
- Modify: `frontend/src/pages/PromptAdminPage.tsx`

- [ ] Edit→create new version, preview (shows validation result + scaffolded prompt), activate/rollback
      (CAS, shows current active). All diffs/bodies HTML-escaped.
- [ ] `cd frontend && npm run build`; commit.

### Task 14: Docs sync

**Files:**
- Modify: `CLAUDE.md`
- Modify: `backend/CLAUDE.md`
- Modify: `docs/architecture.md`
- Modify: `CHANGELOG.md`
- Modify: `docs/decisions/ADR-001-prompt-store-and-editing-ui.md`

- [ ] Sync root+backend CLAUDE.md, architecture, CHANGELOG with the prompt store (inline-pinning, RBAC,
      audit, IAM split); add an "Implementation (v2 after gate)" note to ADR-001 amending the editable
      surface to "four system bodies only" and recording the inline-pin / server-side-validation decisions.
- [ ] Commit.
