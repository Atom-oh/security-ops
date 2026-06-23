# FSI-Mythos on AgentCore — Design Spec

**Date:** 2026-06-17
**Status:** Approved (brainstorming) → consensus pipeline
**Author:** reconstructed from Robin Insight design docs + live reference deployment

## 1. Purpose

Reconstruct, from design documents only (no source repo was provided), a deployable
full-stack implementation of **FSI-Mythos on AgentCore**: a Claude-based autonomous
security-scanning platform for Korean financial institutions. It reimplements Anthropic
Mythos's 8-Phase agentic scaffold on Amazon Bedrock AgentCore + Strands Agents, fronted by
a React SPA, with Cognito auth, DynamoDB scan history, and Security Hub (ASFF) integration.

Reference inputs (in `reference-docs/`):
- `20260602 - FSI-MythosARCHITECTURE.html` — full technical architecture + lessons (Section 10).
- `20260602 - FSI-Mythos 구현 코드.py` — Python pipeline **stub** (skeleton; methods are `pass`).
- `20260602 - FSI-Mythos - BENCHMARK.html` — validation report (8-CWE corpus, Tier-0/1/2).
- `20260601 - … 적용 방안 - v1/v2.html` — strategy analysis ("Scaffold is the key").
- Live reference: `https://d2emj1i1tsjvuw.cloudfront.net` (us-west-2, acct 243482703270, runtime `fsi_mythos`).

## 2. Scope

In scope (full source reconstruction, deployable, verified by build/synth — not deployed by us
until an explicit go):
1. **Backend** — AgentCore container (Python + Strands Agents), 8-Phase pipeline, action router.
2. **Frontend** — React + Vite (TypeScript) SPA matching the reference UI.
3. **Infra** — Terraform (Seoul `ap-northeast-2`; WAF in `us-east-1`), modules for auth/waf/web/data/ecr/agentcore.
4. **Build/deploy scripts** — ARM64 container build → ECR → `update-agent-runtime`; frontend build; deploy orchestration.
5. **Sample target** — built-in vulnerable corpus covering 8 CWEs.

Out of scope: actual AWS deployment is gated behind one explicit confirmation (target account
180294183052 differs from the reference account; AgentCore/Opus availability in Seoul must be
confirmed at deploy time).

## 3. Architecture

### 3.1 Components
- **Edge/Auth:** CloudFront + OAC (private S3, HTTPS, security headers) · WAF (managed rules,
  rate limit; `CLOUDFRONT` scope ⇒ created in us-east-1) · Cognito (SRP, JWT; email alias,
  Username = UUID) · AgentCore authorizer (Cognito discovery URL + allowed client IDs).
- **Runtime:** AgentCore Runtime (serverless container, JWT inbound auth, microVM session
  isolation) hosting `app.py` (BedrockAgentCoreApp).
- **Pipeline:** 8-Phase multi-agent orchestration (Strands Agents SDK).
- **Sandbox:** AgentCore Code Interpreter for PoC crash reproduction (network-isolated).
- **Data/Model:** Bedrock Opus 4.8/4.7/4.6 (per role) · DynamoDB (per-user scan history) ·
  Security Hub (ASFF findings, optional).

### 3.2 Data flow
Browser → (Cognito **access token**) → AgentCore Runtime `/invocations?qualifier=DEFAULT` →
`app.py` action router:
- `scan` → run 8-Phase pipeline → auto-persist result to DynamoDB (persistence failure is
  isolated: the result is still returned).
- `list_history` → query DynamoDB (newest first).
- `get_scan` → fetch one scan by id.
Static SPA served from S3 (private) via CloudFront + OAC + WAF.

### 3.3 8-Phase pipeline
| Phase | Role | Model | Logic |
|---|---|---|---|
| 0 | Language detect | — | extension map; skip `.git/node_modules/vendor/build` |
| 1 | Sink-guided slicing | — | extract ±20 lines around risky sinks (strcpy/system/eval/…) |
| 2 | File ranking | Ranker · Opus 4.6 | FSI-weighted (auth/crypto/transaction/exposure); sink-density fallback |
| 3 | Agentic hunt ×K | Hunter · Opus 4.7 | independent runs; dedup; frequency→confidence |
| 3.5 | Adversarial self-challenge | Challenger · Opus 4.6 | refute findings; **thinking off**; failure isolated (preserve Hunter findings) |
| 4 | Skeptical validation | Validator · Opus 4.8 | final verdict (confirmed/likely/dismissed/escalate) |
| 6 | Aggregate/report | — | ASFF + CI/CD gate (Critical/High/chaining ⇒ block) |
| 7 | FP memory | — | AgentCore Memory; learn FP patterns |

### 3.4 Data model (DynamoDB `SCAN_HISTORY`)
`userId` (PK, Cognito email) · `scanId` (SK, `createdAt#uuid8`, ScanIndexForward=false) ·
`createdAt` ISO8601 · `projectPath` · `maxFiles` · `passAtK` · `summary`/`report`/`gate`
(JSON strings — floats serialized).

### 3.5 Finding shape
`id (fsi-<sha1[:16]>)` · `title` · `file_path` · `line_range` · `severity`
(critical|high|medium|low|info) · `cwe_id` · `description` · `exploitation_scenario` ·
`patch_suggestion` · `confidence` (0–1) · `chain_potential` · `verdict` · `validated`.

## 4. Key technical decisions (from Architecture §10 lessons)
1. **Model thinking:** Opus 4.7/4.8 require `thinking.type=adaptive` + `output_config.effort`
   (NOT the legacy `thinking.type=enabled` in the stub). Challenger runs thinking **off**.
2. **Region/model profile:** container trusts its `AWS_REGION`; payload `region` is ignored.
   Model IDs are env-configurable. Seoul default uses `apac.anthropic.claude-opus-4-*`
   cross-region inference profiles; us-west-2 fallback uses `us.anthropic.*`.
3. **Inbound auth:** JWT via Cognito; match the **access token** `client_id` claim (ID-token
   `aud` matching caused 401s).
4. **Runtime update:** pushing a new image is not enough — must `update-agent-runtime` to mint
   a new version so DEFAULT serves the new digest.
5. **Local-folder scan:** browser File System Access API reads files → uploaded → materialized
   into a temp dir inside the (isolated) container.

## 4a. Frontend design system
The SPA adopts the existing **"paper + ink + Claude-orange"** token set already in the repo
(`colors.css`, `typography.css`, `spacing.css`): warm paper page (`#FAF9F5`), warm-neutral ink
text, a single Claude-orange brand hue (`#D97757`) for active nav / primary actions / lead chart
series; system sans UI + system mono for code/IDs; tabular numerals for compared metrics; 4px
spacing grid; cards rounded-lg on white with a soft two-stop warm shadow; Claude-orange focus
ring; gentle ease-out motion. These token files become `frontend/src/styles/` (CSS custom
properties; no Tailwind — the stale `tailwind.config.ts` navy/cyan theme is not used). `DESIGN.md`
is the design reference; `index.html` (dark doc-hub) is a separate reference-doc landing page.

## 5. Repository layout
```
backend/   app.py · pipeline/ (config, orchestrator, phase0..7) · agents/ (prompts, models)
           · tools/ (sandbox, history) · sample-target/ · Dockerfile (ARM64) · requirements.txt · tests/
frontend/  Vite+TS · src/ (auth, api/agentcore.ts, pages: Scan/History/Result, components) · .env.example
infra/     modules/ (auth, waf, web, data, ecr, agentcore) · envs/seoul/ (main, variables, outputs, backend)
scripts/   build_push_backend.sh · build_frontend.sh · deploy.sh
docs/      specs/ · plans/
reference-docs/  original design HTML + stub .py
```

## 6. Deployment risks (gating, deploy-time only)
- **AgentCore Runtime + `apac.*` Opus profiles in Seoul** may not be available at deploy time.
  Region and model IDs are variables ⇒ fall back to us-west-2 by changing variables only.
- **AgentCore has no first-class Terraform resource.** The `agentcore` module uses
  `null_resource` + `local-exec` wrapping the AWS CLI (`create/update-agent-runtime`); state
  is reconciled via triggers on the image digest. Documented as a known seam.
- Target account 180294183052 (role `mgmt-vpc-VSCode-Role`) — IAM permissions for Bedrock/
  AgentCore/CloudFront/Cognito/WAF must be confirmed before apply.

## 7. Security mandates (enforced during implementation)
No `0.0.0.0/0` ingress on sensitive ports; no `Principal:"*"` without conditions; no secrets in
code/env committed to git; S3 buckets private (OAC only); WAF enabled on the CloudFront dist;
least-privilege IAM for the runtime execution role (Bedrock invoke, DynamoDB on the one table,
Code Interpreter, Memory). The platform performs **defensive** vulnerability discovery only.

## 8. Verification (no AWS deploy)
- `terraform fmt -check` + `terraform validate` per env.
- Frontend: `npm ci` + `vite build` (typecheck).
- Backend: `python -m compileall`, import smoke, `pytest` (pipeline unit tests with mocked Bedrock).
- Backend container: `docker build` (ARM64) succeeds.
