# FSI-Mythos — Scan Stall Fix (durable async + liveness) — rev2 (post P2 gate)

Base/trunk: `master` · Branch: `feat/fsi-mythos` · Method: TDD + Tidy. Backend tests mock
AWS via injected `deps` + `botocore` Stubber. No live-AWS calls in tests.

## Root cause (panel-confirmed)
`scan_async` runs the 8-phase scan in an in-process **daemon thread** (`_default_spawn`) and
returns `IN_PROGRESS`. On **AgentCore Runtime** the entrypoint is request/response: after
`handler` returns, the microVM is frozen/reaped, killing the thread mid-Phase-3 (multi-minute
Bedrock Hunter). No heartbeat / staleness guard / durable worker → stuck `IN_PROGRESS` forever.

## Panel-driven corrections (P2 gate, unanimous CHANGES-REQUIRED)
- AgentCore `InvokeAgentRuntime` is request/response — **no `InvocationType=Event`**. Durable
  execution must live **off** the request-scoped runtime → **SQS (+DLQ) → worker**. A
  self/async re-invoke or an in-invocation `scan_worker` would be reaped the same way.
- Heartbeat must be **intra-phase** (Phase 3 alone can exceed 15 min); staleness is **advisory**
  (never overwrites canonical `status`) and the threshold is **configurable** and generous.
- The worker must carry a **trusted `user_id`** in its message (don't re-derive from JWT).
- Unit tests prove *logic/routing*, not durability → add `botocore` Stubber tests + a staging
  smoke checklist. Live SQS/worker/IAM verification is a deploy step, not a unit test.
- Delete the false `_default_spawn` docstring ("container persists … unlike Lambda").

## Scope split
- **Now (this plan):** liveness (T1+T2) — the immediate "is it stuck?" UX fix, fully testable —
  plus the durable-dispatch **code seam** (T3: SQS enqueue + idempotent worker + identity
  propagation, Stubber-tested) and infra (T4) + staging checklist (T5).
- **Out of scope (linked):** the `userId=anonymous` JWT-claims-extraction bug. T3 *propagates*
  the parent-resolved `user_id`; fixing claim extraction is a separate ticket.

---

### Task 1: Intra-phase heartbeat
**Files:** Modify `backend/pipeline/orchestrator.py` (accept optional `heartbeat` callable,
call it inside the Phase-3 per-file/per-pass loop), `backend/app.py` (wire heartbeat →
`update_status(updatedAt=now)`), `backend/tools/history.py` (`update_status` stamps `updatedAt`).
Test: `backend/tests/test_history.py`, `backend/tests/test_orchestrator_v2.py`.
- [ ] `update_status` stamps caller-supplied `updated_at`; orchestrator invokes `heartbeat()`
  at least once per hunted file (not only per phase). Heartbeat errors are swallowed.
- [ ] Tests: heartbeat fires >1× during a multi-file Phase-3; `updatedAt` written.
- [ ] Commit.

### Task 2: Advisory staleness on read (no perpetual IN_PROGRESS)
**Files:** Create `backend/tools/staleness.py` (`annotate_stale(record, now_iso, stale_after_sec)`),
Modify `backend/app.py` (apply on `scan_status`/`scan_list` reads). Config: `STALE_AFTER_SEC`
(default 1800, > worst-case single phase). Test: `backend/tests/test_staleness.py`.
- [ ] Pure `annotate_stale`: an `IN_PROGRESS` whose `updatedAt` (fallback `createdAt`) is older
  than `stale_after_sec` gets `statusView="timed_out"` + `stale=true` + reason; **canonical
  `status` is NOT mutated** (a late real completion still wins). Missing timestamps → stale
  (fail-closed). done/error untouched.
- [ ] Tests: stale→advisory timed_out; fresh→unchanged; terminal untouched; missing ts→stale.
- [ ] Commit.

## P2 round-2 corrections (rev3)
- **Worker compute = Fargate/ECS (long-running consumer), NOT Lambda** — Lambda's 900s ceiling
  reproduces the >15min Phase-3 freeze. The worker runs `_run_scan` **in-process**; it must
  never call back into the AgentCore runtime (which would be reaped again).
- `scan_worker` is **private to the SQS consumer** — it is NOT a routable public `route()`
  action (a public action would let a caller forge `user_id`). Identity comes only from the
  trusted enqueued message written server-side.
- **Lease/claim-token idempotency** — SQS is at-least-once; on receive, the worker conditionally
  claims the record (`status IN_PROGRESS AND lease empty/expired → set lease=token,leaseExpiry`);
  duplicate/expired-visibility deliveries that don't win the claim are no-ops; final write is
  conditional on owning the lease. DLQ after `maxReceiveCount`.
- **Heartbeat in the worker** — `scan_worker` passes the same `heartbeat` callback into
  `_run_scan`, else a healthy long scan trips the advisory staleness view.
- **Dispatch-failure compensation** — if SQS enqueue fails after the `IN_PROGRESS` write,
  immediately persist `status="error"` (`error="dispatch_failed"`) so no new stuck record.

### Task 3: Durable dispatch seam — SQS enqueue + idempotent Fargate worker
**Files:** Modify `backend/app.py` (add `SqsDispatchSpawn`; `scan_async` enqueues
`{scanId, user_id, payload}` and acks only on enqueue success; add `scan_worker` action that
runs `_run_scan` synchronously and persists; keep daemon-thread `_default_spawn` for local/test
only; delete the false docstring). Test: `backend/tests/test_app_async.py` (fakes + Stubber).
- [ ] `scan_async` with a durable spawn dispatches a `scan_worker` message (does NOT complete
  in-thread); message carries the trusted `user_id`. Enqueue failure → persist `error`
  (`dispatch_failed`), never leave a bare `IN_PROGRESS`.
- [ ] `scan_worker` (consumer-only entry, not a public `route` action): claims the record via a
  conditional lease token, passes the `heartbeat` into `_run_scan`, persists `done`/`error`
  conditional on owning the lease; non-winning duplicate deliveries are no-ops; robust outer
  try/except; DLQ after `maxReceiveCount`.
- [ ] Stubber test: `SqsDispatchSpawn.send_message` body; enqueue-failure path writes `error`;
  lease claim wins once and duplicate is a no-op.
- [ ] Commit.

### Task 4: Infra — SQS queue + DLQ + Fargate worker
**Files:** `infra/modules/...` (SQS main queue + DLQ, `visibility_timeout > max_scan`,
`maxReceiveCount`); **Fargate/ECS** long-running consumer (NOT Lambda — its 900s cap reproduces
the freeze) with env + least-priv IAM (sqs receive/delete on the queue, dynamodb update on
SCAN_HISTORY, bedrock invoke). The worker process runs `_run_scan` in-process and never
re-invokes the AgentCore runtime.
- [ ] `terraform validate` passes. (Apply is a deploy step.)
- [ ] Commit.

### Task 5: Verify + staging checklist + cleanup
**Files:** `docs/VERIFICATION.md`.
- [ ] `bash tests/run-all.sh` green; record results.
- [ ] Staging smoke checklist: deploy SQS+worker, run a real upload scan, confirm it reaches
  `done` (not stuck), and a forced-kill mid-scan lands in DLQ → surfaced as timed_out.
- [ ] Operationally clean the one already-stuck record (out-of-band DynamoDB update).
- [ ] Commit.
