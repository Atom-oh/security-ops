# CLAUDE.md

Project context for Claude Code. Keep this current — it is loaded into context each session.

## Project

**FSI-Mythos on AgentCore** — a Claude/Amazon Bedrock autonomous security-scanning platform for
Korean financial institutions. An 8-phase multi-agent pipeline (Anthropic Mythos scaffold) finds
and validates source-code vulnerabilities, with an optional cross-family GPT-5.5 ensemble. Live in
Seoul (`ap-northeast-2`).

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12 (3.9-compatible), Strands Agents + Amazon Bedrock AgentCore, boto3 |
| Models | Claude Opus 4.8/4.7/4.6 (`global.*` inference profiles); OpenAI GPT-5.5 via Bedrock `bedrock-mantle` (cross-family ensemble) |
| Frontend | React 18 + Vite + TypeScript, Cognito SRP (amazon-cognito-identity-js); CSS-variable design system (no Tailwind) |
| Infra | Terraform (Seoul + us-east-1 WAF): Cognito, S3+CloudFront+OAC, WAFv2, DynamoDB, ECR, AgentCore runtime, SQS scan-worker |
| Tests | pytest (Bedrock/AWS mocked, moto for DynamoDB) |

## Project structure

```
backend/      AgentCore container — app.py (router), pipeline/ (8 phases), agents/, tools/, sample-target/, Dockerfile (ARM64)
frontend/     React+Vite SPA — src/{auth, api, pages, components, styles}
infra/        Terraform — modules/{data, auth, web, waf, ecr, agentcore} + envs/seoul/
scripts/      deploy.sh, build_push_backend.sh, build_frontend.sh
docs/         architecture, specs/, plans/, decisions/ (ADR), runbooks/, reference/, VERIFICATION.md
tests/        run-all.sh aggregate gate (backend pytest + vite build + terraform validate)
reference-docs/  original design inputs (gitignored — third-party)
```

## Key commands

```bash
# Backend tests (Bedrock mocked)
cd backend && pytest

# Frontend build (typecheck + vite)
cd frontend && npm run build

# Terraform validate
cd infra/envs/seoul && terraform init -backend=false && terraform validate

# Aggregate gate
bash tests/run-all.sh

# Deploy (Seoul) — bootstrap ECR → push ARM64 image → update-agent-runtime → SPA sync/invalidation
AWS_REGION=ap-northeast-2 ./scripts/deploy.sh
# Backend-only redeploy:   ./scripts/build_push_backend.sh
# Frontend-only redeploy:  ./scripts/build_frontend.sh
```

## Conventions

- **Defensive only**: the platform discovers/explains vulns and proposes patches — never weaponized exploits.
- Backend stays **Python 3.9-compatible** (`from __future__ import annotations`, `typing.Optional`); runtime is 3.12.
- Bedrock: trust the container `AWS_REGION` (ignore payload region); `thinking.type=adaptive` + `output_config.effort` for Opus 4.7/4.8; Challenger runs thinking-off.
- Identity comes ONLY from the verified bearer JWT (`sub`) — never from the request payload.
- Scanned code is **untrusted data**: wrap in a per-call random-nonce block; never let it instruct an agent.
- Every external dependency (Bedrock, DynamoDB, sandbox, OpenAI) is **injected** into the pipeline → unit-testable with fakes.
- Gate is **fail-closed**: Critical/High/chaining/incomplete-coverage block.
- **Editable prompts (ADR-001)**: the 4 agent *system* prompts are versioned in DynamoDB and pinned inline at scan-creation; the nonce scaffolding + an immutable safety preamble stay in code, admin routes are gated by verified `cognito:groups`, and the scan-worker IAM role is denied `PROMPT#*`.

## Deploy facts (Seoul, account 180294183052)

- SPA: CloudFront dist `E2HLLA3INF82G9` · Cognito pool `ap-northeast-2_isvS8ctbu`
- AgentCore runtime `fsi_mythos` · DynamoDB `SCAN_HISTORY` · ECR `fsi-mythos`
- Terraform state is **local** (`infra/envs/seoul/terraform.tfstate`, gitignored).

<!-- AUTO-MANAGED:references -->
## Implementation References
- `docs/reference/` — per-layer implementation notes (infrastructure, iac, api, frontend, ui, security, agent-llm)
<!-- /AUTO-MANAGED:references -->

## Auto-sync rules

When code changes alter architecture, commands, or conventions, update this file and
`docs/architecture.md` in the same change. Module-level `CLAUDE.md` files document each top-level
source directory; keep them in sync when a module's responsibility shifts.
