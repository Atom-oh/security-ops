# Changelog

[![English](https://img.shields.io/badge/lang-English-blue.svg)](#english) [![한국어](https://img.shields.io/badge/lang-한국어-red.svg)](#korean)

---

<a id="english"></a>

# English

All notable changes to this project will be documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Cross-family ensemble (Phase 4.5): independent OpenAI GPT-5.5 re-judge via Bedrock `bedrock-mantle` (SigV4/IAM, in-AWS); both-confirm→CONFIRMED, disagree→ESCALATE.
- Deterministic risk triage (Phase 2) and secret pre-filter (Phase 2.5, CWE-798); repo-wide coverage report.
- Per-role and ensemble model selection in the scan form; live per-phase progress detail (language detect → file triage → per-file hunt).
- Expandable finding detail with severity/verdict badge pills and a `remediation` (권장 조치) field.
- Durable async dispatch seam (SQS scan-worker + DLQ) with heartbeat/staleness guards.
- Project scaffolding: `CLAUDE.md` (root + modules), `docs/architecture.md`, ADR/runbook templates.

### Changed
- Cost-DoS budget guard fills with smaller high-risk files instead of aborting on one oversized file.
- Frontend upload sends code files only, bounded by count and total bytes.

### Fixed
- **Security:** identity derived from the verified bearer JWT (`sub`), never the request payload; prompt-injection hardening (random-nonce untrusted-code blocks).
- AgentCore `Ineffectual token` 401 — proactively refresh the Cognito token near expiry.
- Blank-screen crashes during async polling and history view (guard empty IN_PROGRESS records, undefined gate fields).
- Files without a hardcoded sink are still hunted (whole-file fallback) — fixes "scan ends instantly".

## [0.1.0] - 2026-06-17

### Added
- Initial FSI-Mythos on AgentCore: 8-phase pipeline (language detect → sink slicing → ranking → Hunter → Challenger → Validator → ASFF/CI-CD gate → FP memory), React+Vite SPA, Terraform infra (Cognito, S3+CloudFront+OAC, WAF, DynamoDB, ECR, AgentCore runtime), ARM64 container, deploy scripts. Deployed to Seoul (ap-northeast-2).

[Unreleased]: https://github.com/Atom-oh/security-ops/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Atom-oh/security-ops/releases/tag/v0.1.0

---

<a id="korean"></a>

# 한국어

이 프로젝트의 모든 주요 변경 사항은 이 파일에 기록됩니다.
이 문서는 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)를 기반으로 하며,
[Semantic Versioning](https://semver.org/spec/v2.0.0.html)을 따릅니다.

## [Unreleased]

### Added
- 교차패밀리 앙상블(Phase 4.5): Bedrock `bedrock-mantle`(SigV4/IAM, AWS 내부) 경유 OpenAI GPT-5.5 독립 재판정; 양 패밀리 확인→CONFIRMED, 불일치→ESCALATE.
- 결정적 위험 트리아지(Phase 2)와 시크릿 사전필터(Phase 2.5, CWE-798); 레포 전체 커버리지 리포트.
- 스캔 폼의 역할별·앙상블 모델 선택; 단계별 라이브 진행 상세(언어 감지 → 파일 선정 → 파일별 헌트).
- 심각도/판정 배지 + 권장 조치(remediation) 필드를 갖춘 발견 상세 펼침.
- 내구성 비동기 디스패치 시드(SQS scan-worker + DLQ)와 heartbeat/staleness 가드.
- 프로젝트 스캐폴딩: `CLAUDE.md`(루트+모듈), `docs/architecture.md`, ADR/runbook 템플릿.

### Changed
- 비용 DoS 예산 가드: 거대 파일 하나로 중단하지 않고 더 작은 고위험 파일로 채움.
- 프론트 업로드는 코드 파일만, 개수·총 바이트로 제한.

### Fixed
- **보안:** 식별자를 검증된 베어러 JWT(`sub`)에서 도출(요청 payload 사용 금지); 프롬프트 인젝션 격리(랜덤 nonce 코드 블록).
- AgentCore `Ineffectual token` 401 — Cognito 토큰 만료 임박 시 선제 갱신.
- 비동기 폴링·이력 보기 중 빈 화면 크래시 수정(빈 IN_PROGRESS 레코드·undefined 게이트 필드 가드).
- 하드코딩 싱크 없는 파일도 헌트(전체 파일 폴백) — "스캔이 즉시 끝나는" 문제 수정.

## [0.1.0] - 2026-06-17

### Added
- FSI-Mythos on AgentCore 초기 구현: 8-Phase 파이프라인(언어감지 → 싱크 슬라이싱 → 랭킹 → Hunter → Challenger → Validator → ASFF/CI-CD 게이트 → FP 메모리), React+Vite SPA, Terraform 인프라(Cognito, S3+CloudFront+OAC, WAF, DynamoDB, ECR, AgentCore 런타임), ARM64 컨테이너, 배포 스크립트. 서울(ap-northeast-2) 배포.

[Unreleased]: https://github.com/Atom-oh/security-ops/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Atom-oh/security-ops/releases/tag/v0.1.0
