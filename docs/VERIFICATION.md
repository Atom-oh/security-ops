# Verification

Local build/synth verification for FSI-Mythos (no AWS deploy). Run `bash tests/run-all.sh`
for the aggregate gate.

| Gate | Command | Result |
|------|---------|--------|
| Backend unit tests | `cd backend && pytest` | ✅ 71 passed (Bedrock/AWS mocked; moto for DynamoDB) |
| Frontend typecheck + build | `cd frontend && npm run build` | ✅ `tsc --noEmit` clean, vite built 116 modules |
| Terraform fmt | `terraform fmt -recursive -check infra` | ✅ clean |
| Terraform validate | `cd infra/envs/seoul && terraform init -backend=false && terraform validate` | ✅ Success |
| Backend container | `docker build --platform linux/arm64 backend` | ✅ builds; `import app` OK, AgentCore app present |
| Aggregate | `bash tests/run-all.sh` | ✅ ALL GATES PASSED |

## v2.1 (2026-06-18) — backend triage + coverage + prefilter + injection hardening

- Backend unit tests: **99 passed** (added risk_score, phase2.5 prefilter, prompt-injection,
  budget guard, orchestrator-v2, app-v2 suites).
- Frontend `npm run build`: ✅ (coverage UI + client byte-budget).
- Terraform validate + docker build: ✅ (unchanged).
- Consensus gates: P2 plan gate + P4 final gate (codex/agy/gemini) — fixes applied
  (nonce-delimiter injection hardening, entropy FP control, budget `continue`, payload base64
  headroom). Chair rejected one shared false-positive (sandbox `target.code`).

## Test coverage (backend)

- `config` — Finding id determinism, severity ordering, enum values.
- `phase0` language detect, `phase1` sink slicing (incl. word-boundary + line-range parsing).
- `models`/`bedrock` — region→profile, adaptive-thinking fields, region trust, block parsing.
- `phase2` ranker (fallback, hallucination filter), `phase3` hunter (pass@k dedup, robust line_range),
  `phase35` challenger (per-finding isolation), `phase4` validator (verdict mapping).
- `phase6` ASFF + fail-closed gate, `phase7` FP memory, `history` (moto), `sandbox`.
- `orchestrator` end-to-end (all phases mocked), `app` router (CORS, sync/async, impersonation guard).

## Not covered here (deploy-time)

- Actual AWS deploy (`terraform apply`, image push, `update-agent-runtime`).
- AgentCore Runtime + `apac.*` Opus inference-profile availability in `ap-northeast-2`
  (confirm at deploy; fall back to `us-west-2`/`us.*` via `-var region=`).
- Exact `bedrock-agentcore-control` CLI flag shapes (see `infra/modules/agentcore/README.md`).
