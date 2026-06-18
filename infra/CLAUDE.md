# infra/ — Terraform

Seoul (`ap-northeast-2`) infrastructure; WAF in `us-east-1` (CLOUDFRONT scope) via a provider alias.

## Layout
- `modules/data` — DynamoDB `SCAN_HISTORY` (PITR, SSE) + SQS scan-worker queue/DLQ.
- `modules/auth` — Cognito pool (email alias, SRP, no secret) + outputs issuer/discovery URL.
- `modules/web` — private S3 + CloudFront + OAC + security-headers; full public-access-block.
- `modules/waf` — WAFv2 WebACL (CLOUDFRONT, managed rules + rate limit) via `aws.useast1` alias.
- `modules/ecr` — repo + lifecycle + scan-on-push + AgentCore pull policy (SourceAccount-scoped).
- `modules/agentcore` — least-priv exec IAM role + `null_resource` CLI seam (create/update-agent-runtime, JWT authorizer). No first-class TF resource — see module README.
- `envs/seoul/` — composes modules; model-profile vars; local state backend.

## Rules
- Version-pinned providers (`versions.tf`, aws ~> 5.60). No `0.0.0.0/0`, no `Principal:"*"` without conditions, no public S3, no secrets in code.
- AgentCore + Opus availability in Seoul must be confirmed at deploy; region/model are variables (us-west-2 fallback).

## Commands
```bash
cd infra/envs/seoul && terraform init -backend=false && terraform validate && terraform fmt -check -recursive ../..
