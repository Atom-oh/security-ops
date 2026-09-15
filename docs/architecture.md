# Architecture

## System Overview

FSI-Mythos on AgentCore is a Claude/Amazon Bedrock platform that autonomously scans source code
for security vulnerabilities for Korean financial institutions. A React SPA (behind CloudFront +
WAF + Cognito) invokes a Bedrock AgentCore Runtime that executes an 8-phase multi-agent pipeline;
results and per-user history persist in DynamoDB. An optional cross-family GPT-5.5 ensemble
re-judges findings, all within the AWS boundary.

## Components by layer

| Layer | Components |
|-------|------------|
| Presentation | React + Vite SPA on private S3; CloudFront + OAC; WAFv2 (us-east-1) |
| Security/Auth | Cognito (SRP, JWT); AgentCore JWT authorizer; runtime SigV4/IAM |
| Processing | AgentCore Runtime container — 8-phase pipeline (Strands Agents); SQS scan-worker (durable async) |
| Model | Bedrock Opus 4.8/4.7/4.6 (`global.*` profiles); GPT-5.5 via `bedrock-mantle` |
| Storage | DynamoDB `SCAN_HISTORY` (per-user `sub`); ECR (ARM64 image); AgentCore Memory (FP) |
| Observability | CloudWatch logs (per-phase progress, timing, tracebacks) |

## Architecture diagram

```
                          ┌──────────────────────────┐
   Browser (SPA) ───TLS──▶│ CloudFront + WAF + OAC    │──▶ private S3 (React build)
        │                 └──────────────────────────┘
        │ Authorization: Bearer <Cognito access JWT>
        ▼
┌──────────────────────────────┐      ┌──────────────────────┐
│ AgentCore Runtime  /invocations│◀JWT─│ Cognito (SRP, authz) │
│  app.route → 8-phase pipeline  │      └──────────────────────┘
│  P0 lang→P1 sink→P2 risk triage│
│  →P3 Hunter→P3.5 Challenger     │──InvokeModel──▶ Bedrock Opus (global.*)
│  →P4 Validator→P4.5 ensemble    │──SigV4───────▶ bedrock-mantle → GPT-5.5
│  →P6 ASFF+gate →P7 FP memory    │
└───────┬──────────────┬─────────┘
        │              │
        ▼              ▼
  DynamoDB        AgentCore Code Interpreter (PoC sandbox)
  SCAN_HISTORY    + SQS scan-worker (durable async dispatch)
```

## Data flow

Login (Cognito) → SPA POST `/invocations` (Bearer JWT) → router resolves `sub` → detect → sink-slice
→ deterministic risk triage (pick scan targets) → Hunter ×k → Challenger → Validator → (optional
GPT-5.5 ensemble vote) → ASFF + fail-closed CI/CD gate → persist to DynamoDB (per-user) → SPA polls/renders.

## Infrastructure (Terraform modules)

| Module | Responsibility |
|--------|----------------|
| data | DynamoDB scan history + SQS scan-worker/DLQ |
| auth | Cognito user pool + SPA client + issuer outputs |
| web | private S3 + CloudFront + OAC + security headers |
| waf | WAFv2 WebACL (CLOUDFRONT, us-east-1) |
| ecr | image repo + lifecycle + AgentCore pull policy |
| agentcore | exec IAM role + create/update-agent-runtime CLI seam |

## Key design decisions

- **Deterministic risk triage before LLM** — score every file (sink density, FSI path/data signals, taint surface, language weight) so a large repo's riskiest files are chosen, not an arbitrary subset. Decouples coverage from token cost.
- **Cross-family ensemble as escalation, not default** — independent epistemic check (GPT-5.5) reserved for opt-in deep audits; disagreement escalates rather than silently dropping.
- **In-AWS for OpenAI, but cross-region by default** — GPT-5.5 via `bedrock-mantle` (SigV4/IAM, no public-internet egress, no stored key) stays inside AWS, but its default endpoint (`openai_region=us-east-2`) is **outside the in-region boundary** (`ap-northeast-2`). Under the v2 design's data-residency veto, the ensemble is therefore **default OFF**: a UI toggle alone is not enough — ops must set `ENSEMBLE_ALLOWED=1` at deploy time to permit cross-region egress, and every enabled scan logs a `DATA-RESIDENCY` audit line recording what left the boundary. The compliant target is an in-boundary endpoint (Azure-KR / SageMaker-Seoul); until one is wired, leave the ensemble disabled.
- **Fail-closed gate** — Critical/High/chaining/incomplete-coverage block; never report a partial scan as clean.
- **Scanned code is untrusted** — per-call nonce boundaries distinguish source data from trusted instructions; they do not prove prompt-injection immunity.
- **Editable prompts, pinned inline (ADR-001)** — the 4 agent *system* prompts are versioned in DynamoDB (immutable versions + CAS active pointer + audit) and **resolved into the scan record/SQS message at creation time**, so a running scan is reproducible and the worker hash-verifies the bodies without reading the store. The nonce scaffolding and an immutable safety preamble stay in code; admin edit/activate is gated by verified `cognito:groups` and a server-side preview/validate gate; the scan-worker IAM role is explicitly denied `PROMPT#*`.

## Operations

See `docs/runbooks/` for deploy/rollback and incident procedures, and `docs/VERIFICATION.md` for the
local gate results.

## Repository review controls

The repository PR-review pipeline is separate from the product scanning/chaining
gate above. Its configured specialists, immutable source/receipt binding and
conditional chair are defined in [the review contract](pr-review-specialists.md).
Model prose uses fenced code examples and symbol/path references; format and
confidentiality checks run before publication. Invalid coverage cannot become PASS.
This presentation policy does not change application models or scan authorization.
