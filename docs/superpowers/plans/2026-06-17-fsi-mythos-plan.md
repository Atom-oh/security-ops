# FSI-Mythos on AgentCore — Implementation Plan

Spec: `docs/superpowers/specs/2026-06-17-fsi-mythos-design.md`
Base/trunk: `master` · Working branch: `feat/fsi-mythos`
Method: TDD + Tidy First. Each task is bite-sized, lists exact files, ends in one commit.
Backend tests mock Bedrock/boto3 (no network). Frontend/Terraform tasks are gated by
build/validate rather than unit tests.

---

### Task 1: Backend skeleton + tooling

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/requirements.txt`
- Create: `backend/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `tests/run-all.sh`

- [ ] Add pyproject (pytest + ruff config) and requirements (strands-agents, bedrock-agentcore, boto3, pytest, moto).
- [ ] `tests/run-all.sh` runs backend pytest and reports gracefully with zero tests.
- [ ] Commit.

### Task 2: Domain types

**Files:**
- Create: `backend/pipeline/__init__.py`
- Create: `backend/pipeline/config.py`
- Test: `backend/tests/test_config.py`

- [ ] `Severity`, `Verdict`, `Language` enums; `ScanConfig`; `Finding` with `make_id()` = `fsi-<sha1[:16]>`.
- [ ] Tests: id determinism, defaults, severity ordering.
- [ ] Commit.

### Task 3: Phase 0 language detection

**Files:**
- Create: `backend/pipeline/phase0_languages.py`
- Test: `backend/tests/test_phase0.py`

- [ ] `detect_languages(path)`: extension map; exclude `.git/node_modules/vendor/build`.
- [ ] Tests: mapping, exclusions, mixed tree.
- [ ] Commit.

### Task 4: Phase 1 sink-guided slicing

**Files:**
- Create: `backend/pipeline/phase1_slicing.py`
- Test: `backend/tests/test_phase1.py`

- [ ] `sink_guided_slice(file, language)`: per-language sink lists; ±20 line context windows.
- [ ] Tests: detect strcpy/system/eval; empty when no sinks.
- [ ] Commit.

### Task 5: Model/region resolver

**Files:**
- Create: `backend/agents/__init__.py`
- Create: `backend/agents/models.py`
- Test: `backend/tests/test_models.py`

- [ ] Role→model-id map; region→profile prefix (`apac.*` for ap-northeast-2, `us.*` for us-west-2);
  build `additionalModelRequestFields` with `thinking.type=adaptive`+`output_config.effort`; thinking-off variant.
- [ ] Tests: region→prefix, thinking on/off.
- [ ] Commit.

### Task 6: Prompts

**Files:**
- Create: `backend/agents/prompts.py`
- Test: `backend/tests/test_prompts.py`

- [ ] HUNTER/CHALLENGER/VALIDATOR/RANKER system prompts (FSI-weighted, defensive-only) + formatters.
- [ ] Tests: formatters fill placeholders; no unfilled braces.
- [ ] Commit.

### Task 7: Bedrock client wrapper

**Files:**
- Create: `backend/agents/bedrock.py`
- Test: `backend/tests/test_bedrock.py`

- [ ] `converse` wrapper: read `AWS_REGION` (ignore payload region); parse thinking+text blocks → `{thinking,output}`.
- [ ] Tests: mock boto3; assert region trust + parse.
- [ ] Commit.

### Task 8: Phase 2 ranker

**Files:**
- Create: `backend/pipeline/phase2_ranker.py`
- Test: `backend/tests/test_phase2.py`

- [ ] `rank_files(...)`: call wrapper; sink-density fallback; top-N cap.
- [ ] Tests (mocked): ranking, fallback, cap.
- [ ] Commit.

### Task 9: Phase 3 hunter

**Files:**
- Create: `backend/pipeline/phase3_hunter.py`
- Test: `backend/tests/test_phase3.py`

- [ ] `hunt(...)`: ×K independent runs; dedup by file+line+cwe; frequency→confidence.
- [ ] Tests (mocked): dedup + confidence.
- [ ] Commit.

### Task 10: Phase 3.5 challenger

**Files:**
- Create: `backend/pipeline/phase35_challenger.py`
- Test: `backend/tests/test_phase35.py`

- [ ] `challenge(...)`: thinking off; exception isolation (preserve hunter findings on failure).
- [ ] Tests: refute drops finding; raised error swallowed; findings preserved.
- [ ] Commit.

### Task 11: Phase 4 validator

**Files:**
- Create: `backend/pipeline/phase4_validator.py`
- Test: `backend/tests/test_phase4.py`

- [ ] `validate(...)`: final verdict; set confidence + validated.
- [ ] Tests (mocked): verdict mapping.
- [ ] Commit.

### Task 12: Phase 6 report + CI/CD gate

**Files:**
- Create: `backend/pipeline/phase6_report.py`
- Test: `backend/tests/test_phase6.py`

- [ ] `to_asff`, `generate_report`, `cicd_gate_check` (Critical/High/chaining ⇒ BLOCKED).
- [ ] Tests: ASFF shape, counts, gate block/pass.
- [ ] Commit.

### Task 13: Phase 7 FP memory

**Files:**
- Create: `backend/pipeline/phase7_fpmemory.py`
- Test: `backend/tests/test_phase7.py`

- [ ] AgentCore Memory interface + in-memory fake; read/update FP patterns.
- [ ] Tests: record + recall FP pattern.
- [ ] Commit.

### Task 14: History tool (DynamoDB)

**Files:**
- Create: `backend/tools/__init__.py`
- Create: `backend/tools/history.py`
- Test: `backend/tests/test_history.py`

- [ ] `save_scan/list_history/get_scan`: JSON-serialize summary/report/gate; userId PK / scanId SK; newest-first.
- [ ] Tests (moto/stub): save→list→get round trip; serialization.
- [ ] Commit.

### Task 15: Sandbox tool

**Files:**
- Create: `backend/tools/sandbox.py`
- Test: `backend/tests/test_sandbox.py`

- [ ] `verify_poc_in_sandbox` via Code Interpreter interface + fake; invoked only when enabled.
- [ ] Tests: enabled path uses fake; disabled path no-op.
- [ ] Commit.

### Task 16: Orchestrator

**Files:**
- Create: `backend/pipeline/orchestrator.py`
- Test: `backend/tests/test_orchestrator.py`

- [ ] `FSIMythosPipeline.run()` wiring phases 0→7; persistence isolation.
- [ ] Tests (phases mocked): end-to-end dict shape; persistence failure still returns result.
- [ ] Commit.

### Task 17: AgentCore entrypoint

**Files:**
- Create: `backend/app.py`
- Test: `backend/tests/test_app.py`

- [ ] `BedrockAgentCoreApp` action router (`scan/list_history/get_scan`); local-upload materialization to temp dir.
- [ ] Tests: route dispatch; unknown action error; region from env.
- [ ] Commit.

### Task 18: Sample-target corpus

**Files:**
- Create: `backend/sample-target/transfer.c`
- Create: `backend/sample-target/auth.py`
- Create: `backend/sample-target/queries.py`
- Create: `backend/sample-target/files.py`
- Create: `backend/sample-target/crypto.py`
- Create: `backend/sample-target/serial.py`
- Create: `backend/sample-target/render.js`
- Create: `backend/sample-target/README.md`
- Test: `backend/tests/test_sample_target.py`

- [ ] 8-CWE vulnerable samples (CWE-120/78/787 + 89 SQLi, 22 path-traversal, 327 weak-crypto, 502 deser, 79 XSS, 347 auth bypass).
- [ ] Tests: phase0+phase1 detect expected sinks across corpus.
- [ ] Commit.

### Task 19: Dockerfile

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/.dockerignore`

- [ ] ARM64 python:3.12-slim, non-root, install requirements, run app.
- [ ] Verify `docker build --platform linux/arm64` succeeds (gate).
- [ ] Commit.

### Task 20: Vite+TS scaffold

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/.env.example`

- [ ] Scaffold app with env vars (VITE_REGION, VITE_USER_POOL_ID, VITE_USER_POOL_CLIENT_ID, VITE_RUNTIME_ARN).
- [ ] Verify `npm ci && npm run build`.
- [ ] Commit.

### Task 21: Cognito auth

**Files:**
- Create: `frontend/src/auth/cognito.ts`
- Create: `frontend/src/auth/AuthContext.tsx`
- Create: `frontend/src/pages/LoginPage.tsx`

- [ ] SRP login via amazon-cognito-identity-js; token store; logout; access-token getter.
- [ ] Verify build/typecheck.
- [ ] Commit.

### Task 22: AgentCore API client

**Files:**
- Create: `frontend/src/api/agentcore.ts`
- Create: `frontend/src/api/types.ts`

- [ ] Bearer call to Runtime `/invocations?qualifier=DEFAULT` with access token; `scan/listHistory/getScan`.
- [ ] Verify build.
- [ ] Commit.

### Task 23: Scan page

**Files:**
- Create: `frontend/src/pages/ScanPage.tsx`
- Create: `frontend/src/components/ScanForm.tsx`

- [ ] Source select, path, max files, pass@k, per-role models, sandbox toggle, sync/async, estimate.
- [ ] Verify build.
- [ ] Commit.

### Task 24: Pipeline + results

**Files:**
- Create: `frontend/src/pages/ResultView.tsx`
- Create: `frontend/src/components/PipelineProgress.tsx`
- Create: `frontend/src/components/ScanSummary.tsx`
- Create: `frontend/src/components/FindingsTable.tsx`
- Create: `frontend/src/components/CicdGate.tsx`

- [ ] Render phases, summary, findings table, CI/CD gate banner.
- [ ] Verify build.
- [ ] Commit.

### Task 25: History page + layout

**Files:**
- Create: `frontend/src/pages/HistoryPage.tsx`
- Create: `frontend/src/components/Header.tsx`
- Create: `frontend/src/components/Sidebar.tsx`
- Create: `frontend/src/styles.css`

- [ ] History table; header/sidebar; hash routing (`#scan/#history`).
- [ ] Verify build.
- [ ] Commit.

### Task 26: Terraform data module

**Files:**
- Create: `infra/modules/data/main.tf`
- Create: `infra/modules/data/variables.tf`
- Create: `infra/modules/data/outputs.tf`

- [ ] DynamoDB table (PK userId, SK scanId, PAY_PER_REQUEST, PITR).
- [ ] Verify `terraform validate`.
- [ ] Commit.

### Task 27: Terraform auth module

**Files:**
- Create: `infra/modules/auth/main.tf`
- Create: `infra/modules/auth/variables.tf`
- Create: `infra/modules/auth/outputs.tf`

- [ ] Cognito user pool (email alias) + app client (no secret, SRP) + domain; outputs pool/client/discovery URL.
- [ ] Verify validate.
- [ ] Commit.

### Task 28: Terraform web module

**Files:**
- Create: `infra/modules/web/main.tf`
- Create: `infra/modules/web/variables.tf`
- Create: `infra/modules/web/outputs.tf`

- [ ] Private S3 + CloudFront + OAC + security-headers response policy (no public ACLs).
- [ ] Verify validate.
- [ ] Commit.

### Task 29: Terraform WAF module

**Files:**
- Create: `infra/modules/waf/main.tf`
- Create: `infra/modules/waf/variables.tf`
- Create: `infra/modules/waf/outputs.tf`

- [ ] WAFv2 WebACL (CLOUDFRONT scope, managed rules, rate limit) via us-east-1 provider alias.
- [ ] Verify validate.
- [ ] Commit.

### Task 30: Terraform ECR module

**Files:**
- Create: `infra/modules/ecr/main.tf`
- Create: `infra/modules/ecr/variables.tf`
- Create: `infra/modules/ecr/outputs.tf`

- [ ] Private ECR repo + lifecycle policy + scan-on-push.
- [ ] Verify validate.
- [ ] Commit.

### Task 31: Terraform AgentCore module

**Files:**
- Create: `infra/modules/agentcore/main.tf`
- Create: `infra/modules/agentcore/variables.tf`
- Create: `infra/modules/agentcore/outputs.tf`
- Create: `infra/modules/agentcore/README.md`

- [ ] Least-priv execution IAM role (Bedrock invoke, DynamoDB on the table, Memory, Code Interpreter)
  + `null_resource` CLI wrapper (`create/update-agent-runtime`, JWT authorizer) triggered on image digest.
- [ ] Verify validate; document the seam in module README.
- [ ] Commit.

### Task 32: Seoul env wiring

**Files:**
- Create: `infra/envs/seoul/main.tf`
- Create: `infra/envs/seoul/variables.tf`
- Create: `infra/envs/seoul/outputs.tf`
- Create: `infra/envs/seoul/backend.tf`

- [ ] Compose all modules with `ap-northeast-2` + `us-east-1` (WAF) providers; model-profile vars.
- [ ] Verify `terraform init -backend=false && terraform validate && terraform fmt -check`.
- [ ] Commit.

### Task 33: Build/deploy scripts

**Files:**
- Create: `scripts/build_push_backend.sh`
- Create: `scripts/build_frontend.sh`
- Create: `scripts/deploy.sh`

- [ ] buildx ARM64 → ECR → `update-agent-runtime`; frontend build; ordered deploy (apply + sync + invalidation).
- [ ] Verify `bash -n` lint.
- [ ] Commit.

### Task 34: README + run docs

**Files:**
- Create: `README.md`

- [ ] Architecture, prerequisites, region/model config, deploy steps, Seoul/us-west-2 fallback, cost note.
- [ ] Verify referenced paths exist.
- [ ] Commit.

### Task 35: Full verification pass

**Files:**
- Create: `docs/VERIFICATION.md`

- [ ] Run all gates: backend pytest, `vite build`, `terraform validate` (all envs), backend `docker build`.
- [ ] Record results in `docs/VERIFICATION.md`; fix any failures.
- [ ] Commit.
