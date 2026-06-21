# Design Spec: KB-Augmented Context (RAG) for the Scanning Pipeline

- **Status**: Approved (brainstorming) — ready for implementation plan
- **Date**: 2026-06-20
- **Related**: ADR-001 (versioned prompt store); a follow-up ADR-002 may record this decision
- **Working language note**: Korean labels appear where they are injected verbatim into prompts.

## 1. Problem & Goal

The 8-phase pipeline reasons about customer source code with **no knowledge of the organization's
own security posture** — its internal security standards, secure-coding policies, risk-acceptance
criteria, and compliance obligations (e.g. 금융보안원 가이드, ISMS-P). Findings are therefore
generic, not calibrated to what *this* organization treats as critical or acceptable.

**Goal**: Add an Amazon Bedrock managed Knowledge Base over a single internal corpus of security
and policy documents, retrieve the relevant context at scan time, and inject it into the Ranker,
Hunter, and Validator agents so their prioritization, detection, and severity verdicts reflect
the organization's policy — all without leaving the Seoul region and without weakening the
existing prompt-injection and fail-closed controls.

## 2. Locked Decisions (from brainstorming)

| Decision | Choice |
|----------|--------|
| Tenancy | **Single internal corpus** — one Knowledge Base, no multi-tenant isolation |
| Injection points | **Ranker (phase 2), Hunter (phase 3), Validator (phase 4)**; Challenger excluded (keep adversarial step injection-free) |
| Document management | **Admin UI upload** in the existing SPA admin area (alongside the prompt store) |
| Retrieval strategy | **Hybrid (C)**: one shared "policy digest" retrieval per scan for Ranker + Hunter; per-finding targeted retrieval in Validator only |
| KB role | **Advisory augmentation, escalate-only** — never weakens the fail-closed gate (never dismisses or downgrades a finding below its KB-free verdict/severity) |

## 3. Architecture & Components

### 3.1 Knowledge Base (infra) — new Terraform module `infra/modules/knowledge`

- **S3 data source bucket** `kb-docs`: versioned, SSE-KMS, private (no public/OAC access). Holds
  the raw policy/security documents.
- **Bedrock managed Knowledge Base** pointing at the bucket. "Managed" means AWS provisions and
  operates the vector store — no self-managed OpenSearch Serverless / Aurora to run. Embeddings
  via a Bedrock embedding model (e.g. Titan Text Embeddings v2), chunking handled by the KB.
- **Ingestion**: an ingestion/sync job runs after uploads/deletes to (re)index the corpus.
- **Region/availability — verify before deploy**: confirm Bedrock **managed** KB is available in
  `ap-northeast-2`. If it is not yet:
  - **Fallback**: standard Bedrock Knowledge Base backed by **Amazon OpenSearch Serverless**
    (vector collection) in `ap-northeast-2`. The Terraform module is written so the vector
    backend is a swappable submodule/variable; the backend code (the retriever) is unaffected
    because it only calls the `Retrieve` API. The fallback is the explicitly chosen candidate.
    The OSS collection MUST ship with explicit **encryption, network, and data-access policies** —
    the network policy restricts access (no public access; reachable only by the Bedrock KB
    service role / the deployment's VPC endpoint), honoring the no-public-access mandate. (Note:
    the network-policy/VPC-endpoint shape depends on the runtime's VPC posture, confirmed at
    implementation — see §9.)

### 3.2 Retriever abstraction (backend) — new `backend/tools/kb_retriever.py`

- Follows the project's dependency-injection convention (like Bedrock/DynamoDB/sandbox), so the
  pipeline takes a retriever instance and unit tests pass a **fake**.
- Interface:
  ```python
  class Chunk:  # dataclass
      text: str
      source_uri: str
      score: float

  class KbRetriever:
      def retrieve(self, query: str, k: int = 5, *, timeout_s: float = 3.0) -> List[Chunk]: ...
  ```
- Wraps the Bedrock `Retrieve` API (knowledge-base id from env/config). Returns trusted internal
  policy text with source citations and relevance scores.
- **Resilience built in**: on timeout, throttling, empty corpus, or any error it returns `[]`
  (never raises into the pipeline). The caller treats `[]` as "no KB context".

### 3.3 Pipeline wiring (orchestrator + phases)

- **Shared policy-digest retrieval (once per scan)**: the orchestrator builds a query from
  `detected_languages + sink_types + repo_name`, calls `retrieve()` once, and caches the top-K
  chunks on the run object as the "policy digest".
- **Ranker (phase 2)**: policy digest injected into the ranker user prompt so file prioritization
  reflects the org's critical assets/systems.
- **Hunter (phase 3)**: policy digest injected into the hunter user prompt. Hunter runs ×K
  parallel hunters per file; they **share the cached digest** — no extra retrieval calls.
- **Validator (phase 4)**: for each finding (capped at top-N, see §5), a targeted `retrieve()`
  keyed on `finding.title + cwe_id`, **cached by `cwe_id`** within the scan, injected into the
  validator prompt. **Gate-isolation (escalate-only)**: the verdict/severity that the fail-closed
  gate consumes is computed **without letting KB weaken it** — KB may *raise* severity or
  *strengthen* a verdict and may add an advisory `policy_note`, but it may **never** move a finding
  to `DISMISSED` nor lower severity/verdict below the KB-free result. The gate reads the
  KB-free-or-escalated value, so KB cannot suppress a blocking finding. This resolves the apparent
  tension between "calibrate severity" and "never a gate input": calibration is **one-directional
  (escalate)** for anything the gate consumes.

### 3.4 Admin UI (frontend) — extend the existing SPA admin

A "정책 문서 (Policy Documents)" tab next to the prompt-store screens:
- Document list: name, size, uploaded-by, ingestion status, last-synced timestamp.
- Upload: request a presigned S3 PUT URL → PUT the object → **call `kb_ingest`** to start the
  ingestion job. Ingestion is triggered **after** the object exists (never at URL-issue time),
  avoiding the race where indexing starts before the upload completes.
- Delete: remove from S3 and from the KB index.
- Sync status: show ingestion-job state (queued / indexing / ready / failed).
- Gated by the **same admin Cognito group** as the prompt store (ADR-001 RBAC).
- **`uploaded_by` is derived server-side** from the verified JWT (`cognito:username`/`sub`) when
  `kb_upload_url`/`kb_ingest` is called and recorded in a server-side manifest — never taken from
  the payload or from client-set S3 object metadata (identity convention).

### 3.5 API routes (`backend/app.py`)

All admin-gated by verified `cognito:groups` (never from payload):
- `kb_list_docs` — list corpus documents + ingestion status (from the server-side manifest).
- `kb_upload_url` — return a scoped, short-lived presigned S3 PUT URL; record `uploaded_by` +
  pending-manifest entry server-side from the verified JWT.
- `kb_ingest` — start the Bedrock ingestion job for an uploaded object (called after the PUT
  completes); idempotent per object.
- `kb_delete_doc` — delete object + de-index + manifest removal.
- `kb_sync_status` — ingestion-job status.

The scan path uses the retriever internally; it adds **no new public route**.

## 4. Data Flow

1. Admin uploads `policy.pdf` via the SPA → presigned PUT to `kb-docs` → ingestion job → chunked
   + embedded into the managed vector store.
2. Scan starts (Fargate worker) → orchestrator builds the policy-digest query → `retrieve()` →
   top-K trusted chunks cached on the run.
3. Ranker + Hunter prompts receive the shared digest block (labeled trusted; see §6).
4. Validator, per finding (top-N capped, CWE-cached) → targeted `retrieve()` → severity/verdict
   calibrated against policy.

## 5. Error Handling, Cost & Resilience

- **Advisory-only invariant**: KB unavailable / `Retrieve` failure / empty corpus → the pipeline
  proceeds **without** KB context. KB output is augmentation, **never** a fail-closed gate input.
  A KB outage must not change the gate outcome. This is a tested invariant (§7).
- **Gate-isolation invariant**: even when KB *is* present, KB content can only escalate (§3.3) —
  a KB fake that tries to dismiss or downgrade a blocking (Critical/High/chaining) finding must
  leave the gate verdict `BLOCKED` unchanged. Tested in §7.
- **Latency**: per-`Retrieve` timeout (default 3 s); on timeout, skip and continue.
- **Token budget**: cap injected KB characters per prompt (default ~4000 chars); drop lowest-score
  chunks first. Reuse the existing `budget_guard` pattern.
- **Cost-DoS guards**: cap `k` (default 5); cap Validator per-finding retrievals to top-N findings
  (default N = 10, by descending pre-validation severity); cache by `cwe_id` so repeated CWEs in
  one scan reuse one retrieval.

These defaults are configurable via `ScanConfig`/env; §9 tracks the values to confirm against
real corpus size and latency during implementation.

## 6. Security & Data Residency

- **Trusted-but-bounded injection**: KB chunks are trusted internal data, so they are **not**
  wrapped in the `<<<UNTRUSTED_CODE>>>` nonce block. They are injected in a separate, clearly
  labeled block — `## 사내 정책 컨텍스트 (신뢰 가능)` — kept distinct from the untrusted-code
  block. The editable system prompts (ADR-001 store) state that policy context is **reference
  only** and must not override analysis instructions or the injection guard. KB content can never
  re-define the system prompt or the nonce scaffolding.
- **Data residency**: KB, vector store, and `kb-docs` S3 bucket all in `ap-northeast-2`. Customer
  code and retrieval queries (derived from code) never leave the region.
- **Encryption**: SSE-KMS on the S3 bucket and KB storage.
- **RBAC**: ingestion/management is admin-only (Cognito group), same enforcement as the prompt
  store.
- **IAM roles** (least-privilege):
  - **Bedrock KB service role** (`Principal: bedrock.amazonaws.com`): `s3:ListBucket` + `s3:GetObject`
    on `kb-docs`, `kms:Decrypt`/`kms:GenerateDataKey` on the bucket's KMS key (required because the
    bucket is SSE-KMS — otherwise ingestion fails `AccessDenied`), and write access to the vector
    backend (managed store, or the OpenSearch Serverless collection on the fallback path).
  - **Admin ingestion role**: `s3:PutObject`/`s3:DeleteObject` on `kb-docs` + `bedrock:StartIngestionJob`.
  - **Scan-worker role — deliberate difference from ADR-001**: ADR-001 denies the worker `PROMPT#*`
    (prompts pinned inline at scan creation). KB retrieval is **code-dependent and cannot be
    pre-resolved at scan creation**, so the worker is granted **`bedrock:Retrieve` (read-only)** on
    the KB only — no KB write/ingestion and no S3 write.

## 7. Testing

- Inject a **fake retriever**; unit-test each of Ranker/Hunter/Validator with and without KB
  context.
- **Invariant test**: KB outage (retriever returns `[]` / raises) does not change the fail-closed
  gate outcome.
- Empty-corpus and timeout fallback paths.
- Token-budget truncation (lowest-score chunks dropped first) and the Validator `cwe_id` cache
  (one retrieval per repeated CWE).
- Admin RBAC on all `kb_*` routes; presigned-URL scoping and expiry.
- `terraform validate` for the new `knowledge` module (both managed-KB and OpenSearch-Serverless
  fallback paths).

## 8. Scope (YAGNI)

**In scope (MVP)**: single KB + S3 data source (managed, with OpenSearch Serverless fallback),
injected retriever, shared policy digest for Ranker/Hunter, per-finding targeted retrieval for
Validator, admin upload/delete/status UI + routes, advisory-only resilience, residency/RBAC/IAM.

**Out of scope (later)**:
- Per-finding policy **provenance** display in the UI / finding records.
- A dedicated **reranking** model (rely on managed-KB default ranking first).
- **Hunter per-finding/per-file targeted retrieval** — Hunter uses the shared digest only, to keep
  the ×K hunter cost flat. Revisit if Hunter precision needs it.
- Multi-tenant / per-customer KB isolation (single corpus by decision).

## 9. Open Items to Confirm at Implementation

1. Bedrock **managed KB** availability in `ap-northeast-2` (else OpenSearch Serverless fallback).
2. Embedding model choice + its `ap-northeast-2` availability.
3. Concrete values: `k`, Validator top-N, per-prompt KB char budget, `Retrieve` timeout.
4. Supported document formats for the corpus (PDF/Markdown/HTML/text) and max object size.
