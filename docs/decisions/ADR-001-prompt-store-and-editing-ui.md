# ADR-001: Versioned Prompt Store and Admin Editing UI for Pipeline Agents

<a href="#english"><img src="https://img.shields.io/badge/lang-English-blue.svg" alt="English"></a>
<a href="#korean"><img src="https://img.shields.io/badge/lang-한국어-red.svg" alt="Korean"></a>

---

<a id="english"></a>

# English

## Status

Accepted

> Co-authored with the co-agent panel (Kiro + Codex responded; Antigravity timed out). Both
> responders independently converged on the decision below; Claude chaired and broke the one
> open split (where to resolve the active version) in favor of scan-creation-time pinning.

## Context

The 8-phase scanning pipeline runs four LLM agents — Ranker, Hunter, Challenger, Validator —
whose system prompts and user-prompt builders live as Python module-level constants in
`backend/agents/prompts.py`. Each phase imports its prompt directly
(`from agents.prompts import HUNTER_SYSTEM, hunter_user_prompt`).

This means every prompt change requires a code edit, a container rebuild, and an AgentCore
Runtime redeploy. Prompt tuning is the highest-frequency change in an agentic security product:
security engineers want to adjust the Hunter's false-positive guidance or the Validator's
verdict thresholds without a deploy cycle, compare wordings, and roll back instantly when a
change regresses scan quality. The current design makes that loop slow and risky, and it leaves
no audit trail of who changed a prompt or when.

We need to externalize the four editable agent prompts to a server-side store with version
history, expose an admin UI to edit and roll them back, and have the pipeline pick up the active
version on the next scan — without a redeploy. Two constraints are non-negotiable:

1. The prompt-injection scaffolding (nonce-wrapped untrusted-code blocks, the untrusted-data
   preamble, delimiter defanging) is a security control, not content, and must remain in code
   and always be applied around any stored prompt.
2. Only the four known agent keys may be edited — no arbitrary keys — and editing is restricted
   to administrators.

The stack already provides a DynamoDB table (scan history) and S3 (the SPA bucket), so the
choice of backend should weigh reuse against fit.

## Options Considered

### Option 1: DynamoDB-backed prompt store (chosen)

Store prompts in DynamoDB. Items are immutable versions keyed by agent; a separate item holds
the active-version pointer per agent, updated with a conditional write.

- **Pros**: Reuses existing DynamoDB infra and access patterns; single-digit-millisecond reads
  for active-version lookup; conditional writes give atomic, race-free active-pointer updates
  and optimistic concurrency on edits; cheap to model immutable version history (one item per
  version) with author/timestamp metadata for the audit trail; encryption and PITR already
  enabled on the table pattern.
- **Cons**: 400 KB item-size limit (ample for prompts, but a hard ceiling); no native object
  versioning, so the version scheme must be modeled explicitly in keys; querying full version
  history requires a deliberate key design.

### Option 2: S3-backed prompt store

Store each prompt as an object in a versioned S3 bucket, relying on S3 native object versioning.

- **Pros**: Native, automatic object versioning; no item-size concerns; cheap storage.
- **Cons**: No atomic "set active version" primitive — S3 has no conditional compare-and-swap
  across objects, so an active pointer needs a separate consistent store anyway; higher and
  more variable read latency than DynamoDB for the per-scan active lookup; building an audit
  index and listing versions with metadata is clumsier than a DynamoDB query.

### Option 3: Hybrid — S3 content + DynamoDB metadata/index

Store prompt bodies in S3 and version/active/audit metadata in DynamoDB.

- **Pros**: Removes the item-size ceiling; keeps atomic pointers and queryable history in
  DynamoDB.
- **Cons**: Two stores to keep consistent (write-ordering and orphan-cleanup concerns); two
  reads on the hot path; more moving parts and IAM surface for no real benefit at prompt sizes
  that fit comfortably in a DynamoDB item.

## Decision

Adopt **Option 1: a DynamoDB-backed, immutable, versioned prompt store** with an admin editing
UI in the existing React SPA, and resolve the active prompt version **at scan-creation time**.

Data model (single table, reusing the existing pattern):

```text
PK = PROMPT#<agentKey>         # agentKey ∈ {ranker, hunter, challenger, validator}
SK = V#<zero-padded-version>   # immutable version item: body, author, createdAt, note
SK = ACTIVE                    # pointer item: activeVersion, updatedBy, updatedAt
```

- **Allowlist**: `agentKey` is constrained to the four known agents server-side; arbitrary keys
  are rejected.
- **Immutability + rollback**: version items are append-only and never mutated. Editing creates
  a new version. "Activate" and "roll back" are the same operation — a conditional write that
  repoints `ACTIVE` to an existing version (compare-and-swap on the prior pointer to prevent
  lost updates).
- **Injection scaffolding stays in code**: stored content is only the editable system/user-prompt
  text. `build_untrusted_block`, `untrusted_preamble`, and delimiter defanging remain in
  `backend/agents/prompts.py` and are always wrapped around the stored prompt at call time. The
  store cannot disable or alter them.
- **RBAC**: edit/activate operations require membership in an admin Cognito group, enforced on
  the backend (not just hidden in the UI). Reads of the active prompt for scanning need no admin
  role.
- **Test-before-activate**: a new version can be previewed/dry-run before it is made active, so a
  malformed or regressive prompt never silently becomes the production prompt.
- **Runtime resolution — pinned at scan creation**: when a scan is enqueued, the API resolves and
  records the active version id for each agent into the scan record / SQS message. The Fargate
  worker uses the pinned version for the whole scan. This eliminates both the staleness window
  (no stale cache to invalidate on edit) and the mid-scan race (an activation during a running
  scan cannot change that scan's prompts). The next scan picks up the new active version
  automatically — no redeploy. A code-defined default per agent is the fallback if the store is
  empty or unreachable.

Rationale for the chosen split: Codex argued for resolving the active version once at scan
creation; Kiro proposed a short-TTL cache in the worker. Pinning at creation was chosen because
the TTL approach reintroduces a staleness window and a mid-scan-change race that pinning avoids
outright, at no extra cost.

## Consequences

### Positive

- Security engineers tune prompts and roll back through the UI in seconds, with no rebuild or
  redeploy.
- Full, immutable audit trail (who/when/what) per agent prompt; trivial rollback to any prior
  version.
- Atomic, race-free activation via DynamoDB conditional writes; reuses infra already in the
  stack (table pattern, encryption, PITR).
- A running scan is reproducible: its prompts are pinned, so concurrent edits cannot perturb
  in-flight results.
- The injection-defense scaffolding and the agent allowlist keep the editable surface tightly
  bounded — a compromised or careless edit cannot remove the prompt-injection guard or introduce
  a new agent.

### Negative

- New surface to build and secure: prompt-store table, admin API routes, RBAC enforcement, and
  UI screens (list versions, diff, edit, preview, activate/rollback).
- The 400 KB DynamoDB item limit caps a single prompt version; very large prompts would need a
  redesign (this is far above current prompt sizes).
- A code-level default must be kept in sync as the seed/fallback, so prompts now live in two
  conceptual places (code default + store) until fully migrated.
- Pinning at scan creation means an urgent prompt fix does not affect scans already enqueued or
  running; it applies from the next scan onward.

## References

- `backend/agents/prompts.py` — current hardcoded prompts and injection-guard scaffolding
- `backend/pipeline/phase2_ranker.py`, `phase3_hunter.py`, `phase35_challenger.py`,
  `phase4_validator.py`, `ensemble.py` — prompt consumers
- `infra/modules/data/main.tf` — existing DynamoDB table + SQS scan-worker pattern
- `infra/modules/auth/` — Cognito user pool (admin group for RBAC)
- Co-agent panel session (Kiro + Codex) — multi-AI second opinion that informed this decision

---

<a id="korean"></a>

# 한국어

## 상태

승인됨

> co-agent 패널과 공동 작성했습니다(Kiro + Codex 응답, Antigravity 시간 초과). 두 응답 AI는
> 아래 결정으로 독립적으로 수렴했으며, Claude가 의장으로서 유일하게 남은 쟁점(활성 버전을 어디서
> 확정할지)을 스캔 생성 시점 고정 방식으로 결정했습니다.

## 배경

8단계 스캔 파이프라인은 네 개의 LLM 에이전트(Ranker, Hunter, Challenger, Validator)를 실행하며,
각 에이전트의 시스템 프롬프트와 사용자 프롬프트 빌더는 `backend/agents/prompts.py`에 파이썬 모듈
수준 상수로 들어 있습니다. 각 단계는 프롬프트를 직접 import 합니다
(`from agents.prompts import HUNTER_SYSTEM, hunter_user_prompt`).

따라서 프롬프트를 한 번 바꾸려면 코드 수정, 컨테이너 재빌드, AgentCore Runtime 재배포가 모두
필요합니다. 에이전트형 보안 제품에서 프롬프트 튜닝은 가장 빈번한 변경입니다. 보안 엔지니어는 배포
주기 없이 Hunter의 오탐 억제 지침이나 Validator의 판정 임계값을 조정하고, 문구를 비교하며, 변경이
스캔 품질을 떨어뜨리면 즉시 롤백하고 싶어 합니다. 현재 설계는 이 반복 루프를 느리고 위험하게 만들며,
누가 언제 프롬프트를 바꿨는지에 대한 감사 기록도 남기지 않습니다.

편집 가능한 네 개의 에이전트 프롬프트를 버전 이력이 있는 서버 측 저장소로 외부화하고, 이를 편집하고
롤백하는 관리자 UI를 제공하며, 파이프라인이 재배포 없이 다음 스캔에서 활성 버전을 반영하도록 해야
합니다. 다음 두 가지 제약은 타협할 수 없습니다.

1. 프롬프트 인젝션 방어 골격(논스로 감싼 신뢰 불가 코드 블록, 신뢰 불가 데이터 서문, 구분자
   무력화)은 콘텐츠가 아니라 보안 통제이므로 코드에 남아 있어야 하며, 저장된 어떤 프롬프트에도
   항상 적용되어야 합니다.
2. 알려진 네 개의 에이전트 키만 편집할 수 있어야 하며(임의 키 불가), 편집은 관리자에게만
   허용됩니다.

스택에는 이미 DynamoDB 테이블(스캔 이력)과 S3(SPA 버킷)이 있으므로, 백엔드 선택은 재사용성과
적합성을 함께 고려해야 합니다.

## 검토한 옵션

### 옵션 1: DynamoDB 기반 프롬프트 저장소 (선택)

프롬프트를 DynamoDB에 저장합니다. 항목은 에이전트별로 키가 부여된 불변 버전이며, 별도 항목이
에이전트별 활성 버전 포인터를 보관하고 조건부 쓰기로 갱신합니다.

- **장점**: 기존 DynamoDB 인프라와 액세스 패턴을 재사용; 활성 버전 조회에 한 자릿수 밀리초 읽기;
  조건부 쓰기로 원자적이고 경쟁 없는 활성 포인터 갱신과 편집 시 낙관적 동시성 제공; 작성자/타임스탬프
  메타데이터를 가진 불변 버전 이력(버전당 항목 한 개)을 저렴하게 모델링; 암호화와 PITR이 이미
  테이블 패턴에 적용되어 있음.
- **단점**: 400 KB 항목 크기 제한(프롬프트에는 충분하지만 명확한 상한); 네이티브 객체 버전 관리가
  없어 버전 체계를 키로 명시적으로 모델링해야 함; 전체 버전 이력 조회는 의도적인 키 설계 필요.

### 옵션 2: S3 기반 프롬프트 저장소

각 프롬프트를 버전 관리가 켜진 S3 버킷의 객체로 저장하고 S3 네이티브 객체 버전 관리에 의존합니다.

- **장점**: 자동 네이티브 객체 버전 관리; 항목 크기 걱정 없음; 저렴한 스토리지.
- **단점**: 원자적 "활성 버전 설정" 기본 연산이 없음 — S3에는 객체 간 조건부 비교-교환이 없어
  활성 포인터는 어차피 별도의 일관성 저장소가 필요; 스캔별 활성 조회 시 DynamoDB보다 읽기 지연이
  높고 변동이 큼; 감사 인덱스 구축과 메타데이터를 포함한 버전 목록 조회가 DynamoDB 쿼리보다 번거로움.

### 옵션 3: 하이브리드 — S3 콘텐츠 + DynamoDB 메타데이터/인덱스

프롬프트 본문은 S3에, 버전/활성/감사 메타데이터는 DynamoDB에 저장합니다.

- **장점**: 항목 크기 상한 제거; 원자적 포인터와 조회 가능한 이력을 DynamoDB에 유지.
- **단점**: 일관성을 유지해야 하는 저장소가 둘(쓰기 순서와 고아 객체 정리 문제); 핫 패스에서 읽기
  두 번; DynamoDB 항목에 충분히 들어가는 프롬프트 크기에서는 실익 없이 구성 요소와 IAM 표면만 증가.

## 결정

**옵션 1: DynamoDB 기반의 불변·버전 관리 프롬프트 저장소**를 채택하고, 기존 React SPA에 관리자
편집 UI를 두며, 활성 프롬프트 버전을 **스캔 생성 시점에 확정**합니다.

데이터 모델(기존 패턴을 재사용하는 단일 테이블):

```text
PK = PROMPT#<agentKey>         # agentKey ∈ {ranker, hunter, challenger, validator}
SK = V#<zero-padded-version>   # 불변 버전 항목: body, author, createdAt, note
SK = ACTIVE                    # 포인터 항목: activeVersion, updatedBy, updatedAt
```

- **허용 목록**: `agentKey`는 서버 측에서 알려진 네 에이전트로 제한하며 임의 키는 거부합니다.
- **불변성 + 롤백**: 버전 항목은 추가 전용이며 절대 수정하지 않습니다. 편집은 새 버전을 생성합니다.
  "활성화"와 "롤백"은 동일한 연산으로, 기존 버전으로 `ACTIVE`를 다시 가리키는 조건부 쓰기입니다(이전
  포인터에 대한 비교-교환으로 갱신 손실 방지).
- **인젝션 골격은 코드에 유지**: 저장되는 콘텐츠는 편집 가능한 시스템/사용자 프롬프트 텍스트뿐입니다.
  `build_untrusted_block`, `untrusted_preamble`, 구분자 무력화는 `backend/agents/prompts.py`에
  남아 있으며 호출 시점에 저장된 프롬프트를 항상 감쌉니다. 저장소는 이를 비활성화하거나 변경할 수
  없습니다.
- **RBAC**: 편집/활성화 작업은 관리자 Cognito 그룹 멤버십을 요구하며, UI에서 숨기는 데 그치지 않고
  백엔드에서 강제합니다. 스캔을 위한 활성 프롬프트 읽기에는 관리자 권한이 필요 없습니다.
- **활성화 전 테스트**: 새 버전은 활성화되기 전에 미리보기/드라이런할 수 있어, 잘못되었거나 품질을
  떨어뜨리는 프롬프트가 조용히 프로덕션 프롬프트가 되는 일을 막습니다.
- **런타임 확정 — 스캔 생성 시점 고정**: 스캔이 큐에 등록될 때 API가 각 에이전트의 활성 버전 id를
  확정하여 스캔 레코드/SQS 메시지에 기록합니다. Fargate 워커는 스캔 전체 동안 고정된 버전을
  사용합니다. 이로써 staleness 윈도(편집 시 무효화할 캐시 없음)와 스캔 중 경쟁(실행 중 스캔의
  프롬프트를 활성화가 바꿀 수 없음)을 모두 제거합니다. 다음 스캔은 재배포 없이 새 활성 버전을 자동으로
  반영합니다. 저장소가 비어 있거나 도달 불가하면 에이전트별 코드 정의 기본값으로 폴백합니다.

선택한 쟁점 결정의 근거: Codex는 스캔 생성 시 활성 버전을 한 번 확정하자고 했고, Kiro는 워커에
짧은 TTL 캐시를 두자고 제안했습니다. TTL 방식은 고정 방식이 원천적으로 회피하는 staleness 윈도와
스캔 중 변경 경쟁을 다시 들여오므로, 추가 비용 없이 이를 피하는 생성 시점 고정을 선택했습니다.

## 영향

### 긍정적

- 보안 엔지니어가 재빌드나 재배포 없이 UI에서 수초 내에 프롬프트를 튜닝하고 롤백합니다.
- 에이전트 프롬프트별 완전한 불변 감사 기록(누가/언제/무엇); 임의의 이전 버전으로 손쉬운 롤백.
- DynamoDB 조건부 쓰기로 원자적이고 경쟁 없는 활성화; 스택에 이미 있는 인프라(테이블 패턴, 암호화,
  PITR) 재사용.
- 실행 중 스캔은 재현 가능: 프롬프트가 고정되어 동시 편집이 진행 중 결과를 교란할 수 없음.
- 인젝션 방어 골격과 에이전트 허용 목록이 편집 표면을 엄격히 제한 — 손상되거나 부주의한 편집이
  프롬프트 인젝션 가드를 제거하거나 새 에이전트를 도입할 수 없음.

### 부정적

- 구축·보안해야 할 새 표면: 프롬프트 저장소 테이블, 관리자 API 경로, RBAC 강제, UI 화면(버전 목록,
  diff, 편집, 미리보기, 활성화/롤백).
- DynamoDB 400 KB 항목 제한이 단일 프롬프트 버전을 제한; 매우 큰 프롬프트는 재설계 필요(현재 프롬프트
  크기보다 훨씬 큼).
- 시드/폴백으로 코드 수준 기본값을 동기화해 두어야 하므로, 완전 마이그레이션 전까지 프롬프트가 두
  개념적 위치(코드 기본값 + 저장소)에 존재.
- 스캔 생성 시점 고정은 긴급 프롬프트 수정이 이미 큐에 있거나 실행 중인 스캔에는 적용되지 않음을
  의미; 다음 스캔부터 적용됩니다.

## 참고 자료

- `backend/agents/prompts.py` — 현재 하드코딩된 프롬프트와 인젝션 가드 골격
- `backend/pipeline/phase2_ranker.py`, `phase3_hunter.py`, `phase35_challenger.py`,
  `phase4_validator.py`, `ensemble.py` — 프롬프트 소비자
- `infra/modules/data/main.tf` — 기존 DynamoDB 테이블 + SQS 스캔 워커 패턴
- `infra/modules/auth/` — Cognito 사용자 풀(RBAC용 관리자 그룹)
- co-agent 패널 세션(Kiro + Codex) — 이 결정에 반영된 멀티 AI 2차 의견
