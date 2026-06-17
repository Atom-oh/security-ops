# FSI-Mythos on AgentCore — Implementation Plan

Spec: `docs/superpowers/specs/2026-06-17-fsi-mythos-design.md`
Base/trunk: `master` · Working branch: `feat/fsi-mythos`
Method: TDD + Tidy First. Each task is bite-sized, lists exact files, and ends in one commit.
Backend tests mock Bedrock/boto3 (no network). Frontend/Terraform tasks are gated by
build/validate, not unit tests.

## Files in scope
```
backend/**
frontend/**
infra/**
scripts/**
docs/**
README.md
.gitignore
```

## Milestone 1 — Backend domain core (pure Python, TDD)

- [ ] **T1 · Project skeleton + tooling.** Add `backend/pyproject.toml` (pytest config, ruff),
  `backend/requirements.txt` (strands-agents, bedrock-agentcore, boto3), `backend/__init__.py`,
  `backend/tests/__init__.py`, `tests/run-all.sh` (runs backend pytest + frontend/terraform gates
  when present). Test: `tests/run-all.sh` runs and reports 0 backend tests gracefully.
- [ ] **T2 · Domain types.** `backend/pipeline/config.py`: `Severity`, `Verdict`, `Language`
  enums; `ScanConfig` (project_path, max_files, pass_at_k, model ids per role, region, fsi_mode,
  scan_scope, compliance_tags, sandbox flag); `Finding` dataclass with `make_id()` (`fsi-<sha1[:16]>`).
  Test `backend/tests/test_config.py`: id determinism, defaults, severity ordering.
- [ ] **T3 · Phase 0 language detection.** `backend/pipeline/phase0_languages.py:detect_languages`.
  Test `test_phase0.py`: extension mapping, excludes `.git/node_modules/vendor/build`, mixed tree.
- [ ] **T4 · Phase 1 sink-guided slicing.** `backend/pipeline/phase1_slicing.py:sink_guided_slice`
  (per-language sink lists C/C++/Java/Python/JS; ±20 line context). Test `test_phase1.py`:
  finds strcpy/system/eval, returns context windows, empty when no sinks.

## Milestone 2 — Agents + LLM phases (mocked Bedrock)

- [ ] **T5 · Model/region resolver.** `backend/agents/models.py`: role→model-id map; resolve
  inference profile by region (`apac.*` for ap-northeast-2, `us.*` for us-west-2); helper to build
  Bedrock `additionalModelRequestFields` with `thinking.type=adaptive` + `output_config.effort`,
  and a "thinking off" variant for Challenger. Test `test_models.py`: region→prefix, thinking on/off.
- [ ] **T6 · Prompts.** `backend/agents/prompts.py`: HUNTER/CHALLENGER/VALIDATOR/RANKER system
  prompts (FSI-weighted, defensive-only) as constants + formatters. Test `test_prompts.py`:
  formatters fill placeholders, no unfilled `{}`.
- [ ] **T7 · Bedrock client wrapper.** `backend/agents/bedrock.py`: thin `converse` wrapper that
  reads `AWS_REGION`, ignores payload region, parses thinking+text blocks, returns `{thinking,output}`.
  Test `test_bedrock.py`: mock boto3 client, asserts region trust + parse.
- [ ] **T8 · Phase 2 ranker.** `backend/pipeline/phase2_ranker.py:rank_files` (calls wrapper;
  sink-density fallback when no sinks; returns top-N). Test `test_phase2.py` (mocked): ranking,
  fallback, max_files cap.
- [ ] **T9 · Phase 3 hunter.** `backend/pipeline/phase3_hunter.py:hunt` (×K independent runs,
  dedup by file+line+cwe, frequency→confidence). Test `test_phase3.py` (mocked): dedup + confidence.
- [ ] **T10 · Phase 3.5 challenger.** `backend/pipeline/phase35_challenger.py:challenge`
  (thinking off; exception isolation — on failure preserve hunter findings). Test `test_phase35.py`:
  refute drops finding, raised error is swallowed and findings preserved.
- [ ] **T11 · Phase 4 validator.** `backend/pipeline/phase4_validator.py:validate` (final verdict;
  sets confidence + validated). Test `test_phase4.py` (mocked): verdict mapping.

## Milestone 3 — Reporting, memory, tools

- [ ] **T12 · Phase 6 report + CI/CD gate.** `backend/pipeline/phase6_report.py`: `to_asff(finding)`,
  `generate_report(findings)`, `cicd_gate_check(findings, threshold)` (Critical/High/chaining ⇒ BLOCKED).
  Test `test_phase6.py`: ASFF shape, severity counts, gate block/pass.
- [ ] **T13 · Phase 7 FP memory.** `backend/pipeline/phase7_fpmemory.py`: read/update FP patterns
  via AgentCore Memory client (interface + in-memory fake for tests). Test `test_phase7.py`.
- [ ] **T14 · History tool (DynamoDB).** `backend/tools/history.py`: `save_scan`, `list_history`,
  `get_scan` (JSON-serialize summary/report/gate; userId PK / scanId SK; newest-first).
  Test `test_history.py`: moto or stubbed client; save→list→get round trip; serialization.
- [ ] **T15 · Sandbox tool.** `backend/tools/sandbox.py`: `verify_poc_in_sandbox` via AgentCore
  Code Interpreter (interface + fake). Test `test_sandbox.py`: invoked only when enabled; safe no-op fake.

## Milestone 4 — Orchestrator, entrypoint, corpus

- [ ] **T16 · Orchestrator.** `backend/pipeline/orchestrator.py:FSIMythosPipeline.run()` wiring
  phases 0→7, persistence isolation. Test `test_orchestrator.py` (all phases mocked): end-to-end
  dict shape, persistence failure still returns result.
- [ ] **T17 · AgentCore entrypoint.** `backend/app.py`: `BedrockAgentCoreApp`, action router
  (`scan`/`list_history`/`get_scan`), local-upload materialization to temp dir. Test `test_app.py`:
  route dispatch, unknown action error, region from env.
- [ ] **T18 · Sample-target corpus.** `backend/sample-target/` with 8-CWE vulnerable+clean pairs
  (transfer.c CWE-120/78/787, auth.py CWE-347, plus SQLi/path-traversal/weak-crypto/deser/XSS).
  Test `test_sample_target.py`: phase0+phase1 detect expected sinks across the corpus.

## Milestone 5 — Container

- [ ] **T19 · Dockerfile + entry.** `backend/Dockerfile` (ARM64, python:3.12-slim, non-root,
  installs requirements, runs app), `backend/.dockerignore`. Verify: `docker build --platform
  linux/arm64` succeeds (gate, not unit test).

## Milestone 6 — Frontend foundation

- [ ] **T20 · Vite+TS scaffold.** `frontend/package.json`, `vite.config.ts`, `tsconfig.json`,
  `index.html`, `src/main.tsx`, `src/App.tsx`, `.env.example` (VITE_REGION, VITE_USER_POOL_ID,
  VITE_USER_POOL_CLIENT_ID, VITE_RUNTIME_ARN). Verify: `npm ci && npm run build`.
- [ ] **T21 · Cognito auth.** `frontend/src/auth/` (SRP login via amazon-cognito-identity-js,
  token store, logout). Verify: typecheck/build.
- [ ] **T22 · AgentCore API client.** `frontend/src/api/agentcore.ts`: SigV4-less bearer call to
  Runtime `/invocations?qualifier=DEFAULT` with access token; `scan/listHistory/getScan`. Verify: build.

## Milestone 7 — Frontend UI

- [ ] **T23 · Scan page.** `frontend/src/pages/ScanPage.tsx` + components (source select,
  path, max files, pass@k, per-role models, sandbox toggle, sync/async, estimate). Verify: build.
- [ ] **T24 · Pipeline + results.** `frontend/src/pages/ResultView.tsx`, components
  `PipelineProgress`, `ScanSummary`, `FindingsTable`, `CicdGate`. Verify: build.
- [ ] **T25 · History page + layout.** `frontend/src/pages/HistoryPage.tsx`, `Header`, `Sidebar`,
  routing (hash `#scan/#history`). Verify: build.

## Milestone 8 — Terraform modules

- [ ] **T26 · Data module.** `infra/modules/data/` — DynamoDB table (PK userId, SK scanId,
  PAY_PER_REQUEST, PITR). Verify: `terraform validate` in a fixture.
- [ ] **T27 · Auth module.** `infra/modules/auth/` — Cognito user pool (email alias) + app client
  (no secret, SRP), domain. Outputs pool id, client id, discovery URL. Verify: validate.
- [ ] **T28 · Web module.** `infra/modules/web/` — private S3 + CloudFront + OAC + security-headers
  response policy. Verify: validate (no public ACLs).
- [ ] **T29 · WAF module.** `infra/modules/waf/` — WAFv2 WebACL (CLOUDFRONT scope, managed rules,
  rate limit) under a `us-east-1` provider alias. Verify: validate.
- [ ] **T30 · ECR module.** `infra/modules/ecr/` — private ECR repo + lifecycle policy + scan-on-push.
  Verify: validate.
- [ ] **T31 · AgentCore module.** `infra/modules/agentcore/` — runtime execution IAM role
  (least-priv: Bedrock invoke, DynamoDB on the table, Memory, Code Interpreter) + `null_resource`
  CLI wrapper (`create/update-agent-runtime`, JWT authorizer config) triggered on image digest.
  Verify: validate; documented seam in module README.

## Milestone 9 — Env wiring + scripts

- [ ] **T32 · Seoul env.** `infra/envs/seoul/{main,variables,outputs,backend}.tf` composing all
  modules with `ap-northeast-2` + `us-east-1` (WAF) providers, model-profile vars. Verify:
  `terraform init -backend=false && terraform validate && terraform fmt -check`.
- [ ] **T33 · Build/deploy scripts.** `scripts/build_push_backend.sh` (buildx ARM64 → ECR →
  `update-agent-runtime`), `scripts/build_frontend.sh`, `scripts/deploy.sh` (terraform apply +
  frontend sync + CloudFront invalidation, ordered per Architecture §08). Verify: `bash -n` lint.

## Milestone 10 — Docs + final verification

- [ ] **T34 · README + run docs.** `README.md` (architecture, prerequisites, region/model config,
  deploy steps, Seoul/us-west-2 fallback, cost note). Verify: links/paths exist.
- [ ] **T35 · Full verification pass.** Run all gates: backend pytest, `vite build`, `terraform
  validate` (all envs), backend `docker build`. Fix any failures. Commit verification notes.
