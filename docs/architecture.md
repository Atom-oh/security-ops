[![English](https://img.shields.io/badge/lang-English-blue.svg)](#english) [![한국어](https://img.shields.io/badge/lang-한국어-red.svg)](#한국어)

<a id="english"></a>

# English

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
- **In-AWS only for OpenAI** — GPT-5.5 via `bedrock-mantle` (SigV4/IAM, no public egress, no stored key) keeps data-residency consistent with the `global.*` Claude profiles.
- **Fail-closed gate** — Critical/High/chaining/incomplete-coverage block; never report a partial scan as clean.
- **Scanned code is untrusted** — random-nonce wrapping defeats indirect prompt injection.
- **Editable prompts, pinned inline (ADR-001)** — the 4 agent *system* prompts are versioned in DynamoDB (immutable versions + CAS active pointer + audit) and **resolved into the scan record/SQS message at creation time**, so a running scan is reproducible and the worker hash-verifies the bodies without reading the store. The nonce scaffolding and an immutable safety preamble stay in code; admin edit/activate is gated by verified `cognito:groups` and a server-side preview/validate gate; the scan-worker IAM role is explicitly denied `PROMPT#*`.

## Operations

See `docs/runbooks/` for deploy/rollback and incident procedures, and `docs/VERIFICATION.md` for the
local gate results.

---

<a id="한국어"></a>

# 한국어

## 시스템 개요

FSI-Mythos on AgentCore는 국내 금융사를 위해 소스코드 보안 취약점을 자율 스캔하는 Claude/Amazon
Bedrock 플랫폼입니다. React SPA(CloudFront + WAF + Cognito 뒤)가 Bedrock AgentCore 런타임을 호출해
8-Phase 멀티에이전트 파이프라인을 실행하고, 결과와 사용자별 이력을 DynamoDB에 저장합니다. 선택적
교차패밀리 GPT-5.5 앙상블이 발견을 재판정하며, 모두 AWS 경계 내에서 동작합니다.

## 레이어별 구성요소

| 레이어 | 구성요소 |
|-------|---------|
| 프레젠테이션 | 비공개 S3의 React+Vite SPA; CloudFront+OAC; WAFv2(us-east-1) |
| 보안/인증 | Cognito(SRP, JWT); AgentCore JWT authorizer; 런타임 SigV4/IAM |
| 처리 | AgentCore 런타임 컨테이너 — 8-Phase 파이프라인(Strands); SQS scan-worker(내구성 비동기) |
| 모델 | Bedrock Opus 4.8/4.7/4.6(`global.*`); `bedrock-mantle` 경유 GPT-5.5 |
| 저장 | DynamoDB `SCAN_HISTORY`(사용자별 `sub`); ECR(ARM64); AgentCore Memory(FP) |
| 관측성 | CloudWatch 로그(단계별 진행·소요시간·트레이스백) |

## 아키텍처 다이어그램

```
                          ┌──────────────────────────┐
   브라우저(SPA) ──TLS──▶ │ CloudFront + WAF + OAC    │──▶ 비공개 S3 (React 빌드)
        │                 └──────────────────────────┘
        │ Authorization: Bearer <Cognito access JWT>
        ▼
┌──────────────────────────────┐      ┌──────────────────────┐
│ AgentCore 런타임 /invocations  │◀JWT─│ Cognito (SRP, 인가)  │
│  app.route → 8-Phase 파이프라인 │      └──────────────────────┘
│  P0 언어→P1 싱크→P2 위험 트리아지│
│  →P3 Hunter→P3.5 Challenger     │──InvokeModel──▶ Bedrock Opus (global.*)
│  →P4 Validator→P4.5 앙상블       │──SigV4───────▶ bedrock-mantle → GPT-5.5
│  →P6 ASFF+게이트 →P7 FP 메모리   │
└───────┬──────────────┬─────────┘
        ▼              ▼
  DynamoDB        AgentCore Code Interpreter (PoC 샌드박스)
  SCAN_HISTORY    + SQS scan-worker (내구성 비동기 디스패치)
```

## 데이터 흐름

로그인(Cognito) → SPA가 `/invocations` POST(Bearer JWT) → 라우터가 `sub` 식별 → 언어감지 → 싱크
슬라이싱 → 결정적 위험 트리아지(스캔 대상 선정) → Hunter ×k → Challenger → Validator → (선택적
GPT-5.5 앙상블 투표) → ASFF + fail-closed CI/CD 게이트 → DynamoDB(사용자별) 저장 → SPA 폴링/렌더.

## 인프라 (Terraform 모듈)

| 모듈 | 책임 |
|------|------|
| data | DynamoDB 스캔 이력 + SQS scan-worker/DLQ |
| auth | Cognito 사용자 풀 + SPA 클라이언트 + issuer 출력 |
| web | 비공개 S3 + CloudFront + OAC + 보안 헤더 |
| waf | WAFv2 WebACL(CLOUDFRONT, us-east-1) |
| ecr | 이미지 repo + 라이프사이클 + AgentCore pull 정책 |
| agentcore | 실행 IAM role + create/update-agent-runtime CLI seam |

## 핵심 설계 결정

- **LLM 전 결정적 위험 트리아지** — 모든 파일을 점수화(싱크 밀도·FSI 경로/데이터 신호·테인트 표면·언어 가중)해 대형 레포에서도 위험 상위 파일을 선정. 커버리지와 토큰 비용을 분리.
- **교차패밀리 앙상블은 기본이 아닌 에스컬레이션** — 독립 검증(GPT-5.5)은 opt-in 심층 감사에만; 불일치는 묵살이 아니라 에스컬레이션.
- **OpenAI도 AWS 내부 경유** — `bedrock-mantle`(SigV4/IAM, 공개 송신·저장 키 없음)로 `global.*` Claude와 데이터 거주성 일관성 유지.
- **Fail-closed 게이트** — Critical/High/체이닝/커버리지 부족은 차단; 부분 스캔을 clean으로 보고하지 않음.
- **스캔 코드는 신뢰 불가** — 랜덤 nonce 래핑으로 간접 프롬프트 인젝션 방어.
- **편집 가능 프롬프트, 인라인 고정(ADR-001)** — 4개 에이전트 *system* 프롬프트를 DynamoDB에 버전 관리(불변 버전 + CAS 활성 포인터 + 감사)하고 **스캔 생성 시점에 본문을 스캔레코드/SQS 메시지에 인라인 고정**하여, 진행 중 스캔의 재현성을 보장하고 워커는 스토어를 읽지 않고 해시만 검증. nonce 골격과 고정 안전 preamble은 코드에 유지; 어드민 편집/활성화는 검증된 `cognito:groups`와 서버측 미리보기/검증 게이트로 보호; scan-worker IAM 역할은 `PROMPT#*` 명시적 Deny.

## 운영

배포/롤백·장애 대응은 `docs/runbooks/`, 로컬 게이트 결과는 `docs/VERIFICATION.md` 참고.
