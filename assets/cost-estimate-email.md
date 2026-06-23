# 견적 요청 이메일 초안 (FSI-Mythos)

> 첨부: `cost-architecture.svg` (또는 PNG), 필요 시 `cost-architecture.drawio`
> 수신처에 맞게 [대괄호] 부분만 수정하세요.

---

## 버전 A — AWS 계정팀(SA/AM)에 견적 요청

**받는사람:** [AWS Account Manager / Solutions Architect]
**제목:** [회사명] FSI-Mythos (AgentCore 기반) 월 예상비용 산정 요청 — Seoul(ap-northeast-2)

안녕하세요 [담당자]님,

저희가 Amazon Bedrock AgentCore 기반으로 구축한 금융권 보안 스캐닝 플랫폼
**FSI-Mythos**의 월 운영비 견적을 요청드립니다. 리전은 **ap-northeast-2(서울)**,
계정은 **180294183052** 입니다. 첨부한 아키텍처 다이어그램에 과금 대상 리소스를
정리해 두었습니다.

**견적 대상 리소스**

| 구분 | 리소스 | 과금 단위 |
|------|--------|-----------|
| Edge | AWS WAF (WebACL, CLOUDFRONT/us-east-1, 관리형 룰 3개) | ACL + 룰 + 요청 |
| Edge | CloudFront + OAC | 데이터 전송 + 요청 |
| Edge | S3 (Private SPA 정적 호스팅) | 저장 + 요청 |
| Auth | Cognito User Pool (SRP) | MAU |
| Compute | AgentCore Runtime (8-phase 파이프라인 호스팅) | vCPU·메모리 세션시간 |
| AI | AgentCore Memory (False-Positive 메모리) | 이벤트 저장/검색 |
| AI | AgentCore Code Interpreter (PoC 샌드박스) | 세션 활성시간 |
| Data | DynamoDB (On-Demand, scan history) | R/W 요청 + 저장 |
| Registry | ECR (컨테이너 이미지) | 저장 |

**중요 — 산정 범위:**
- **Bedrock(Claude Opus) 코드 스캔 토큰 비용은 이번 견적에서 제외**해 주세요.
  (스캔 단위로 별도 산정 예정 — 참고치는 스캔당 약 $0.5–3 수준)
- 위 표의 **인프라/플랫폼 리소스 월 예상비용**만 산정 부탁드립니다.

**사용량 가정 (확인/보정 부탁드립니다):**
- 월 활성 사용자(MAU): [예: 50명]
- 월 스캔 횟수: [예: 500회]
- 스캔당 평균 Runtime 세션시간: [예: 5분, vCPU/메모리: 1 vCPU / 2GB]
- 월 CloudFront 데이터 전송량: [예: 5GB]
- DynamoDB 저장/요청 규모: [예: <1GB, 요청 수만 건/월]

가정에 보정이 필요하거나 누락된 항목이 있으면 알려주시고, 가능하시면
**AWS Pricing Calculator 공유 링크** 형태로 회신 주시면 감사하겠습니다.

감사합니다.
[이름 / 직책 / 연락처]

---

## 버전 B — 사내 보고/승인용 (간략)

**제목:** FSI-Mythos 월 인프라 예상비용 견적 (Bedrock 스캔 토큰 별도)

[수신]님,

FSI-Mythos(AgentCore 기반 보안 스캐닝 플랫폼, 서울 리전)의 월 인프라 예상비용
견적을 공유드립니다. 아키텍처와 과금 대상은 첨부 다이어그램을 참고 바랍니다.

- **포함:** WAF · CloudFront · S3 · Cognito · AgentCore Runtime/Memory/Code Interpreter · DynamoDB · ECR
- **제외:** Bedrock(Claude Opus) **코드 스캔 토큰** 비용 — 스캔량 기반 변동비라 별도 산정
  (참고: 스캔당 약 $0.5–3, 월 [N]회 가정 시 약 $[금액])
- **사용량 가정:** MAU [N], 월 스캔 [N]회, Runtime 평균 [N]분/세션

상세 단가표가 필요하시면 회신 부탁드립니다.

감사합니다.
[이름]
