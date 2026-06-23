# FSI-Mythos on AgentCore

Claude-based **autonomous security-scanning platform** for Korean financial institutions. It
reimplements Anthropic Mythos's 8-phase agentic scaffold on **Amazon Bedrock AgentCore** +
**Strands Agents**, fronted by a React SPA, with Cognito auth, DynamoDB scan history, and
Security Hub (ASFF) integration.

> Reconstructed from the design documents in [`reference-docs/`](reference-docs/) (architecture,
> benchmark, analysis, and a stub implementation). See
> [`docs/superpowers/specs/`](docs/superpowers/specs/) for the spec and
> [`docs/superpowers/plans/`](docs/superpowers/plans/) for the implementation plan.

## Architecture

```
Browser ──(Cognito access-token / Bearer)──▶ AgentCore Runtime /invocations
   │                                              │  app.py router: scan · scan_async · list_history · get_scan
   │                                              ├─ 8-phase pipeline (Strands Agents + Bedrock Opus)
CloudFront + WAF + OAC                            ├─ DynamoDB (per-user scan history)
   │  (private S3 SPA)                            ├─ AgentCore Code Interpreter (PoC sandbox)
   └──────────────────────────────────────────── └─ AgentCore Memory (false-positive memory)
```

**8-phase pipeline:** `0` language detect → `1` sink-guided slicing → `2` ranker (Opus 4.6) →
`3` agentic hunter ×K (Opus 4.7) + dedup → `3.5` adversarial challenger (Opus 4.6, thinking-off,
isolated) → `4` skeptical validator (Opus 4.8) → `6` ASFF + fail-closed CI/CD gate → `7` FP memory.

## Layout

| Path | What |
|------|------|
| `backend/` | AgentCore container — Python + Strands Agents, 8-phase pipeline, `app.py` router, sample-target corpus, `Dockerfile` (ARM64) |
| `frontend/` | React + Vite (TS) SPA — Cognito SRP login, scan form, pipeline/results, history; paper+ink+Claude-orange design system |
| `infra/` | Terraform — `modules/` (data, auth, web, waf, ecr, agentcore) + `envs/seoul/` |
| `scripts/` | `deploy.sh`, `build_push_backend.sh`, `build_frontend.sh` |
| `reference-docs/` | original design HTML + stub `.py` |

## Prerequisites

- AWS account + credentials (optionally set `AWS_ROLE_ARN` to assume a deploy role).
- Terraform ≥ 1.5, Docker (with buildx), Node ≥ 18, Python ≥ 3.11 (3.9 OK for tests), `jq`.
- **Bedrock model access** to Claude Opus 4.8/4.7/4.6 in the target region.
- **AgentCore Runtime** available in the target region.

## Region & model configuration

Defaults target **Seoul (`ap-northeast-2`)** for data sovereignty; the container trusts its own
`AWS_REGION` and resolves `apac.*` Claude inference profiles. WAF is created in `us-east-1`
(CLOUDFRONT scope) automatically via a provider alias.

> ⚠️ **Confirm at deploy time** that AgentCore Runtime and the `apac.*` Opus inference profiles
> are available in `ap-northeast-2`. If not, fall back to `us-west-2` by setting
> `-var region=us-west-2` (the app then resolves `us.*` profiles) — **no code changes needed**.

Key variables (`infra/envs/seoul/variables.tf`): `region`, `name_prefix`, `runtime_name`,
`image_uri`, `image_digest`, `model_arns` (scoped to Claude models by default).

## Deploy

```bash
# optional: export AWS_ROLE_ARN=arn:aws:iam::<acct>:role/<deploy-role>
./scripts/deploy.sh          # bootstrap ECR → build+push backend → full apply → build+sync frontend
```

The script prints the public SPA URL (`cloudfront_domain`) at the end. To update only the
backend later: `./scripts/build_push_backend.sh` (rebuilds, pushes, and `update-agent-runtime`s
to the new digest — a plain image push is not enough).

Create the first user (admin-only sign-up pool):

```bash
aws cognito-idp admin-create-user --user-pool-id <pool> --username you@bank.kr \
  --user-attributes Name=email,Value=you@bank.kr Name=email_verified,Value=true
aws cognito-idp admin-set-user-password --user-pool-id <pool> --username you@bank.kr \
  --password '<StrongPassw0rd!>' --permanent
```

## Verify locally (no AWS)

```bash
cd backend && pip install -r requirements.txt && pytest    # 71 unit tests, Bedrock mocked
cd frontend && npm ci && npm run build                     # typecheck + vite build
cd infra/envs/seoul && terraform init -backend=false && terraform validate
bash tests/run-all.sh                                       # aggregate gate
```

## Cost

Pay-per-use: Bedrock Opus inference dominates (~$0.50–$3.00 per scan depending on target size,
`max_files`, and `pass@k`). DynamoDB on-demand, CloudFront/S3/WAF/ECR are minimal at low volume.
AgentCore Runtime bills per session/compute.

## Security posture

Defensive scanning only. Private S3 (OAC + full public-access-block), WAF on CloudFront,
Cognito admin-only sign-up with SRP, least-privilege runtime IAM (Claude models, the one
DynamoDB table, Memory/Code-Interpreter, scoped ECR pull), JWT inbound auth on the runtime
(access-token `client_id` match), and a fail-closed CI/CD gate (Critical/High/chaining ⇒ blocked).
