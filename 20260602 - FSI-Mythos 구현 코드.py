# =============================================================================
# 🔐 FSI-Mythos: 국내 금융사를 위한 Claude 기반 자율 보안 스캐닝 파이프라인
# =============================================================================
# 아키텍처: Mythos Research Edition 8-Phase 파이프라인을 Claude Opus 4.7 +
#           AWS Bedrock으로 재구현한 국내 금융사 특화 버전
#
# 요구사항:
#   - Python 3.11+
#   - AWS Bedrock (Claude Opus 4.7 모델 접근)
#   - Docker (샌드박스 실행 환경)
#   - 약 $0.50-$3.00/스캔 (타겟 크기에 따라)
#
# 참조: github.com/Keyvanhardani/Mythos-research (Apache 2.0)
# =============================================================================

"""
┌─────────────────────────────────────────────────────────────────────────────┐
│                     FSI-Mythos 파이프라인 전체 구조                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Phase 0: 언어 감지  ──►  Phase 1: 싱크 기반 슬라이싱                        │
│       │                        │                                            │
│       ▼                        ▼                                            │
│  Phase 2: 파일 위험도 랭킹  ──►  Phase 2.5: 빌드 샌드박스                    │
│       │                              │                                      │
│       ▼                              ▼                                      │
│  Phase 3: 에이전틱 헌트 (K회 독립 실행)                                      │
│       │                                                                     │
│       ▼                                                                     │
│  Phase 3.5: 적대적 자기 도전 (Self-Challenge)                               │
│       │                                                                     │
│       ▼                                                                     │
│  Phase 4: 회의적 검증 (Skeptical Validator)                                 │
│       │                                                                     │
│       ▼                                                                     │
│  Phase 6: 집계/보고서 + Security Hub 연동                                    │
│       │                                                                     │
│       ▼                                                                     │
│  Phase 7: FP 메모리 기록 (오탐 학습)                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
"""

import json
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

# =============================================================================
# 1. 핵심 설정 및 데이터 모델
# =============================================================================

class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

class Language(Enum):
    C = "c"
    CPP = "cpp"
    JAVA = "java"
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    KOTLIN = "kotlin"  # 금융사 모바일앱
    SWIFT = "swift"

@dataclass
class ScanConfig:
    """FSI-Mythos 스캔 설정"""
    project_path: str
    max_files: int = 10              # 타겟 파일 수 (비용 제어)
    pass_at_k: int = 3              # 독립 실행 횟수 (재현성 확보)
    model_id: str = "anthropic.claude-opus-4-7-20260415-v1:0"
    region: str = "ap-northeast-2"  # 서울 리전 (데이터 주권)
    max_tokens: int = 16384
    thinking_budget: int = 50000    # Extended Thinking 예산
    temperature: float = 1.0        # 다양성 확보 (Anthropic 권장)
    sandbox_image: str = "fsi-mythos-sandbox:latest"
    # 금융사 특화 설정
    fsi_mode: bool = True           # 금융 도메인 특화 규칙 활성화
    scan_scope: str = "defensive"   # defensive | full (익스플로잇 제한)
    compliance_tags: list = field(default_factory=lambda: ["K-ISMS", "전자금융감독규정"])

@dataclass  
class Finding:
    """취약점 발견 결과"""
    id: str
    title: str
    file_path: str
    line_range: tuple
    severity: Severity
    cwe_id: Optional[str] = None
    description: str = ""
    proof_of_concept: str = ""
    patch_suggestion: str = ""
    confidence: float = 0.0         # 0-1 (회의적 검증 후 점수)
    chain_potential: bool = False   # 체이닝 가능성
    validated: bool = False


# =============================================================================
# 2. Phase 0: 언어 감지 (Language Detection)
# =============================================================================

SINK_PATTERNS = {
    Language.C: {
        "memory": ["memcpy", "strcpy", "strcat", "sprintf", "gets", "malloc", "realloc", "free"],
        "format_string": ["printf", "fprintf", "sprintf", "snprintf", "syslog"],
        "injection": ["system", "popen", "exec", "execve"],
        "integer": ["atoi", "atol", "strtol", "strtoul"],
        # 금융사 특화: 암호화 관련 싱크
        "crypto": ["EVP_EncryptInit", "EVP_DecryptInit", "RSA_public_encrypt",
                   "AES_encrypt", "HMAC_Init", "SSL_CTX_new"],
    },
    Language.JAVA: {
        "injection": ["Runtime.exec", "ProcessBuilder", "Statement.execute",
                     "PreparedStatement", "createQuery"],
        "deserialization": ["ObjectInputStream", "readObject", "XMLDecoder"],
        "auth": ["getSession", "setAttribute", "SecurityManager"],
        # 금융사 특화: 전자금융 API
        "fsi_api": ["TransferService", "PaymentGateway", "OTPValidator",
                   "TokenGenerator", "SessionManager"],
    },
    Language.PYTHON: {
        "injection": ["eval", "exec", "subprocess", "os.system", "pickle.loads"],
        "path_traversal": ["open", "os.path.join", "send_file"],
        "auth": ["jwt.decode", "session", "login_required"],
    },
    Language.JAVASCRIPT: {
        "xss": ["innerHTML", "document.write", "eval", "dangerouslySetInnerHTML"],
        "injection": ["child_process.exec", "require", "import"],
        "auth": ["jwt.verify", "passport", "session"],
    },
}


def detect_languages(project_path: str) -> dict:
    """
    Phase 0: 프로젝트의 주요 언어와 파일 분포를 감지합니다.
    
    Returns:
        {Language.C: [file1, file2, ...], Language.JAVA: [...], ...}
    """
    import os
    from pathlib import Path
    
    EXTENSIONS = {
        ".c": Language.C, ".h": Language.C,
        ".cpp": Language.CPP, ".cc": Language.CPP, ".hpp": Language.CPP,
        ".java": Language.JAVA,
        ".py": Language.PYTHON,
        ".js": Language.JAVASCRIPT, ".ts": Language.TYPESCRIPT,
        ".kt": Language.KOTLIN, ".swift": Language.SWIFT,
    }
    
    result = {}
    for root, dirs, files in os.walk(project_path):
        # .git, node_modules 등 제외
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", "vendor", "build"}]
        for f in files:
            ext = Path(f).suffix.lower()
            if ext in EXTENSIONS:
                lang = EXTENSIONS[ext]
                if lang not in result:
                    result[lang] = []
                result[lang].append(os.path.join(root, f))
    
    return result


# =============================================================================
# 3. Phase 1: 싱크 기반 슬라이싱 (Sink-Guided Slicing)
# =============================================================================

def sink_guided_slice(file_path: str, language: Language) -> list:
    """
    Phase 1: 위험한 싱크 함수 호출을 포함하는 코드 슬라이스를 추출합니다.
    
    Mythos의 핵심: 단순 패턴 매칭이 아닌, 데이터 흐름을 역추적하여
    사용자 입력이 위험 함수에 도달하는 경로를 식별합니다.
    
    Returns:
        [{"sink": "memcpy", "line": 42, "context": "...", "taint_sources": [...]}]
    """
    import re
    
    sinks = SINK_PATTERNS.get(language, {})
    findings = []
    
    with open(file_path, 'r', errors='ignore') as f:
        lines = f.readlines()
    
    all_sink_funcs = []
    for category, funcs in sinks.items():
        all_sink_funcs.extend([(func, category) for func in funcs])
    
    for i, line in enumerate(lines):
        for func_name, category in all_sink_funcs:
            if func_name in line:
                # 컨텍스트 윈도우 추출 (전후 20줄)
                start = max(0, i - 20)
                end = min(len(lines), i + 20)
                context = "".join(lines[start:end])
                
                findings.append({
                    "sink": func_name,
                    "category": category,
                    "line": i + 1,
                    "file": file_path,
                    "context": context,
                    "context_range": (start + 1, end),
                })
    
    return findings


# =============================================================================
# 4. Phase 2: 파일 위험도 랭킹 (Risk Ranking)
# =============================================================================

RISK_RANKING_PROMPT = """당신은 사이버보안 전문가입니다. 아래 파일 목록을 보안 위험도 순으로 1-5등급으로 분류하세요.

## 평가 기준 (금융사 특화)
- 인터넷 노출 여부 (인터넷뱅킹, API 게이트웨이)
- 인증/인가 로직 포함 여부
- 암호화/복호화 처리 여부
- 금융 거래 처리 여부 (이체, 결제)
- 외부 입력 처리 (사용자 데이터, 파일 업로드)
- 레거시 코드 (오래된 C/C++ 코드)
- 싱크 함수 밀도 (위험 함수 호출 빈도)

## 파일 목록 및 싱크 분석 결과
{file_analysis}

## 출력 형식
각 파일에 대해 JSON 배열로 응답하세요:
[
  {{"file": "path/to/file.c", "rank": 1, "reason": "인터넷 노출 API + 버퍼 조작"}},
  ...
]
rank 1이 가장 위험합니다. 상위 {max_files}개만 반환하세요.
"""


# =============================================================================
# 5. Phase 3: 에이전틱 헌트 (Agentic Hunter)
# =============================================================================

HUNTER_SYSTEM_PROMPT = """당신은 시니어 보안 연구원입니다. 제공된 소스코드에서 보안 취약점을 찾으세요.

## 역할
- 패턴 매칭이 아닌 **의미론적 추론**으로 취약점을 찾습니다
- 코드의 "의도"와 "실제 동작"의 간극을 분석합니다
- 여러 파일/함수에 걸친 **크로스파일 상호작용**을 추적합니다
- 발견한 취약점의 **실제 악용 가능성**을 평가합니다

## 금융사 특화 관점
- 인증 우회: 세션 관리, OTP 검증, 권한 상승
- 거래 무결성: 이중 지불, 경쟁 조건, 금액 조작
- 정보 유출: 민감정보 로깅, 에러 메시지 노출
- 암호화 결함: 키 재사용, 패딩 오라클, 약한 RNG
- API 보안: 인증 누락, 파라미터 변조, 속도 제한 우회

## 분석 방법
1. 코드를 전체적으로 읽고 아키텍처를 파악하세요
2. 데이터 흐름을 추적하세요 (사용자 입력 → 처리 → 출력/저장)
3. 경계 조건과 에러 처리를 집중 분석하세요
4. 취약점을 발견하면 악용 시나리오를 구체적으로 서술하세요
5. PoC(Proof of Concept) 코드를 작성하세요 (방어 목적)

## 출력 형식
각 발견 사항을 다음 JSON으로 보고하세요:
{
  "title": "취약점 제목",
  "severity": "critical|high|medium|low",
  "cwe_id": "CWE-XXX",
  "file": "파일 경로",
  "line_range": [시작줄, 끝줄],
  "description": "상세 설명",
  "exploitation_scenario": "공격 시나리오",
  "proof_of_concept": "PoC 코드",
  "patch_suggestion": "수정 제안",
  "chain_potential": true/false,
  "confidence": 0.0-1.0
}
"""

HUNTER_USER_PROMPT = """## 분석 대상 코드

### 파일: {file_path}
### 위험도 등급: {risk_rank}/5
### 싱크 분석 요약: {sink_summary}

```{language}
{code_content}
```

### 관련 파일 컨텍스트 (호출 관계)
{related_context}

---
이 코드에서 보안 취약점을 찾으세요. 최소한의 false positive로 실제 악용 가능한 취약점만 보고하세요.
"""


# =============================================================================
# 6. Phase 3.5: 적대적 자기 도전 (Adversarial Self-Challenge)
# =============================================================================

CHALLENGER_PROMPT = """당신은 보안 취약점 검증 전문가입니다. 다른 분석가가 보고한 취약점에 대해 
**적대적으로 반박**을 시도하세요.

## 보고된 취약점
{finding_json}

## 원본 코드
```{language}
{code_content}
```

## 당신의 역할
1. 이 취약점이 **실제로 악용 가능한지** 의심하세요
2. 다음을 확인하세요:
   - 컴파일러 최적화로 인해 취약점이 제거되지는 않는지
   - 다른 방어 메커니즘(ASLR, Stack Canary, CFI)으로 차단되지는 않는지
   - 해당 경로가 실제 실행 가능한 경로인지
   - 입력값 제약으로 인해 악용 불가능하지는 않은지
3. 반박에 실패하면(=취약점이 유효하면) "VALID"로 판정
4. 반박에 성공하면 "FALSE_POSITIVE" 이유와 함께 판정

## 출력
{
  "verdict": "VALID" | "FALSE_POSITIVE" | "NEEDS_MORE_INFO",
  "confidence_adjustment": -0.3 ~ +0.2,
  "reasoning": "상세 추론 과정",
  "additional_context_needed": ["필요한 추가 정보"]
}
"""


# =============================================================================
# 7. Phase 4: 회의적 검증 (Skeptical Validator)
# =============================================================================

VALIDATOR_PROMPT = """당신은 보안 취약점 최종 검증자입니다. 이전 두 분석가(Hunter, Challenger)의 
의견을 종합하여 최종 판정을 내리세요.

## Hunter의 보고
{hunter_finding}

## Challenger의 반박
{challenger_response}

## 최종 판정 기준
- CONFIRMED: 취약점이 실제로 악용 가능하고, PoC가 유효함
- LIKELY: 높은 가능성이 있으나 특정 조건에서만 악용 가능
- DISMISSED: 오탐이거나 현실적으로 악용 불가능
- ESCALATE: 수동 검토가 필요한 복잡한 사안

## 금융사 컨텍스트
- 금융 시스템은 24/7 운영, 다운타임 = 직접적 금전 손실
- 규제 준수 위반 시 영업정지 가능
- 고객 데이터 유출 = 신뢰도 붕괴 + 대규모 배상

출력:
{
  "final_verdict": "CONFIRMED|LIKELY|DISMISSED|ESCALATE",
  "final_confidence": 0.0-1.0,
  "severity_adjustment": "변경 시 이유",
  "recommended_action": "즉시패치|계획패치|모니터링|무시",
  "summary": "한 줄 요약"
}
"""


# =============================================================================
# 8. 메인 오케스트레이터 (AWS Step Functions 매핑)
# =============================================================================

class FSIMythosPipeline:
    """
    국내 금융사를 위한 Mythos 파이프라인 메인 오케스트레이터.
    
    AWS 배포 시:
    - Step Functions: 전체 워크플로우 관리
    - ECS Fargate: 격리된 샌드박스 실행
    - Bedrock: Claude Opus 4.7 추론
    - DynamoDB: Finding 저장
    - Security Hub: 결과 통합
    - S3: 보고서/아티팩트 저장
    """
    
    def __init__(self, config: ScanConfig):
        self.config = config
        self.findings: list[Finding] = []
        self.false_positives: list = []  # FP 메모리 (Phase 7)
        
    def run(self) -> dict:
        """전체 파이프라인 실행"""
        
        # Phase 0: 언어 감지
        print("[Phase 0] 언어 감지 중...")
        lang_files = detect_languages(self.config.project_path)
        print(f"  감지된 언어: {[l.value for l in lang_files.keys()]}")
        print(f"  총 파일 수: {sum(len(v) for v in lang_files.values())}")
        
        # Phase 1: 싱크 기반 슬라이싱
        print("\n[Phase 1] 싱크 기반 슬라이싱...")
        all_sinks = []
        for lang, files in lang_files.items():
            for f in files:
                sinks = sink_guided_slice(f, lang)
                all_sinks.extend(sinks)
        print(f"  발견된 싱크: {len(all_sinks)}개")
        
        # Phase 2: 파일 위험도 랭킹 (Claude 호출)
        print("\n[Phase 2] 파일 위험도 랭킹 중...")
        ranked_files = self._rank_files(lang_files, all_sinks)
        target_files = ranked_files[:self.config.max_files]
        print(f"  상위 {len(target_files)}개 파일 선정 완료")
        
        # Phase 2.5: 빌드 샌드박스 (Docker)
        print("\n[Phase 2.5] 샌드박스 환경 준비...")
        # sandbox = self._prepare_sandbox()
        
        # Phase 3: 에이전틱 헌트 (K회 독립 실행)
        print(f"\n[Phase 3] 에이전틱 헌트 ({self.config.pass_at_k}회 실행)...")
        raw_findings = []
        for k in range(self.config.pass_at_k):
            print(f"  Pass {k+1}/{self.config.pass_at_k}...")
            for target in target_files:
                findings = self._hunt(target)
                raw_findings.extend(findings)
        print(f"  원시 발견 수: {len(raw_findings)}개")
        
        # Phase 3.5: 적대적 자기 도전
        print("\n[Phase 3.5] 적대적 자기 도전...")
        challenged = self._challenge(raw_findings)
        
        # Phase 4: 회의적 검증
        print("\n[Phase 4] 회의적 검증...")
        validated = self._validate(challenged)
        self.findings = [f for f in validated if f.validated]
        print(f"  최종 확인된 취약점: {len(self.findings)}개")
        
        # Phase 6: 집계/보고
        print("\n[Phase 6] 보고서 생성 중...")
        report = self._generate_report()
        
        # Phase 7: FP 메모리 기록
        print("\n[Phase 7] FP 메모리 업데이트...")
        self._update_fp_memory(validated)
        
        return report
    
    def _rank_files(self, lang_files: dict, sinks: list) -> list:
        """Phase 2: Claude를 사용한 파일 위험도 랭킹"""
        # 실제 구현에서는 Bedrock Claude 호출
        # file_analysis = self._prepare_file_analysis(lang_files, sinks)
        # response = bedrock_client.converse(...)
        pass
        return []
    
    def _hunt(self, target_file: dict) -> list:
        """Phase 3: 단일 파일에 대한 에이전틱 헌트"""
        # Extended Thinking 활성화하여 Claude 호출
        # 핵심: temperature=1.0으로 다양한 관점 확보
        # 각 실행은 독립적이므로 pass_at_k로 재현성 향상
        pass
        return []
    
    def _challenge(self, findings: list) -> list:
        """Phase 3.5: 각 발견에 대해 적대적 반박 시도"""
        pass
        return findings
    
    def _validate(self, findings: list) -> list:
        """Phase 4: 최종 회의적 검증"""
        pass
        return findings
    
    def _generate_report(self) -> dict:
        """Phase 6: Security Hub ASFF 포맷 보고서 생성"""
        return {
            "total_findings": len(self.findings),
            "critical": len([f for f in self.findings if f.severity == Severity.CRITICAL]),
            "high": len([f for f in self.findings if f.severity == Severity.HIGH]),
            "medium": len([f for f in self.findings if f.severity == Severity.MEDIUM]),
            "low": len([f for f in self.findings if f.severity == Severity.LOW]),
            "findings": self.findings,
        }
    
    def _update_fp_memory(self, all_findings: list):
        """Phase 7: 오탐 패턴을 기록하여 다음 스캔에서 반복 방지"""
        fps = [f for f in all_findings if not f.validated]
        self.false_positives.extend(fps)
        # DynamoDB에 FP 패턴 저장 → 다음 스캔 시 프롬프트에 포함


# =============================================================================
# 9. AWS Bedrock 호출 헬퍼
# =============================================================================

def call_bedrock_with_thinking(
    prompt: str,
    system_prompt: str,
    config: ScanConfig,
    related_files: list = None
) -> dict:
    """
    AWS Bedrock Claude Opus 4.7를 Extended Thinking과 함께 호출합니다.
    
    핵심 설정:
    - Extended Thinking budget: 50,000+ tokens (깊은 추론)
    - Temperature: 1.0 (Extended Thinking 시 필수)
    - 서울 리전: 데이터 주권 보장
    """
    import boto3
    
    client = boto3.client(
        "bedrock-runtime",
        region_name=config.region  # ap-northeast-2 (서울)
    )
    
    # Extended Thinking 설정
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    
    if related_files:
        # 관련 파일 컨텍스트를 추가 (Mythos의 크로스파일 분석 재현)
        context_text = "\n\n".join([
            f"### 관련 파일: {f['path']}\n```\n{f['content']}\n```"
            for f in related_files
        ])
        messages[0]["content"].append({"text": f"\n\n## 관련 파일 컨텍스트\n{context_text}"})
    
    response = client.converse(
        modelId=config.model_id,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={
            "maxTokens": config.max_tokens,
            "temperature": config.temperature,  # Extended Thinking 시 1.0 필수
        },
        additionalModelRequestFields={
            "thinking": {
                "type": "enabled",
                "budget_tokens": config.thinking_budget  # 50,000+ 권장
            }
        }
    )
    
    # 응답 파싱
    result = {"thinking": "", "output": ""}
    for block in response["output"]["message"]["content"]:
        if "thinking" in block:
            result["thinking"] = block["thinking"]["text"]
        elif "text" in block:
            result["output"] = block["text"]
    
    return result


# =============================================================================
# 10. 금융사 특화: CI/CD 통합 인터페이스
# =============================================================================

def cicd_gate_check(findings: list, threshold: dict = None) -> dict:
    """
    CI/CD 파이프라인 게이트 체크.
    CodePipeline / Jenkins에서 호출하여 배포 차단 여부를 결정합니다.
    
    Returns:
        {"pass": bool, "blocking_findings": [...], "advisory_findings": [...]}
    """
    if threshold is None:
        threshold = {
            "block_on_critical": True,
            "block_on_high": True,
            "max_medium_allowed": 3,
            "block_on_chain": True,  # 체이닝 가능 취약점은 항상 차단
        }
    
    blocking = []
    advisory = []
    
    for f in findings:
        if f.severity == Severity.CRITICAL and threshold["block_on_critical"]:
            blocking.append(f)
        elif f.severity == Severity.HIGH and threshold["block_on_high"]:
            blocking.append(f)
        elif f.chain_potential and threshold["block_on_chain"]:
            blocking.append(f)
        else:
            advisory.append(f)
    
    return {
        "pass": len(blocking) == 0,
        "blocking_findings": blocking,
        "advisory_findings": advisory,
        "summary": f"차단: {len(blocking)}건, 참고: {len(advisory)}건"
    }


# =============================================================================
# 11. Security Hub 통합 (ASFF 포맷)
# =============================================================================

def to_security_hub_finding(finding: Finding, account_id: str, region: str = "ap-northeast-2") -> dict:
    """
    발견 사항을 AWS Security Hub ASFF(AWS Security Finding Format)으로 변환합니다.
    기존 보안 운영 워크플로우와 자연스럽게 통합됩니다.
    """
    severity_map = {
        Severity.CRITICAL: {"Label": "CRITICAL", "Normalized": 90},
        Severity.HIGH: {"Label": "HIGH", "Normalized": 70},
        Severity.MEDIUM: {"Label": "MEDIUM", "Normalized": 40},
        Severity.LOW: {"Label": "LOW", "Normalized": 10},
    }
    
    return {
        "SchemaVersion": "2018-10-08",
        "Id": finding.id,
        "ProductArn": f"arn:aws:securityhub:{region}:{account_id}:product/{account_id}/fsi-mythos",
        "GeneratorId": "fsi-mythos-pipeline",
        "AwsAccountId": account_id,
        "Types": ["Software and Configuration Checks/Vulnerabilities/CVE"],
        "CreatedAt": "2026-06-01T00:00:00Z",
        "Severity": severity_map.get(finding.severity, {"Label": "INFORMATIONAL", "Normalized": 0}),
        "Title": finding.title,
        "Description": finding.description,
        "Resources": [{
            "Type": "Other",
            "Id": finding.file_path,
            "Details": {"Other": {"LineRange": str(finding.line_range)}}
        }],
        "Remediation": {
            "Recommendation": {"Text": finding.patch_suggestion}
        },
        "FindingProviderFields": {
            "Confidence": int(finding.confidence * 100),
            "Types": [f"CWE-{finding.cwe_id}"] if finding.cwe_id else [],
        }
    }


# =============================================================================
# 12. 실행 예시
# =============================================================================

if __name__ == "__main__":
    # 금융사 프로젝트 스캔 설정
    config = ScanConfig(
        project_path="/path/to/banking-core-system",
        max_files=8,            # 비용 제어: 상위 8개 파일만
        pass_at_k=3,            # 3회 독립 실행으로 재현성 확보
        region="ap-northeast-2", # 서울 리전
        thinking_budget=50000,   # 깊은 추론 활성화
        fsi_mode=True,
        scan_scope="defensive",  # 방어 목적만
    )
    
    # 파이프라인 실행
    pipeline = FSIMythosPipeline(config)
    report = pipeline.run()
    
    # CI/CD 게이트 체크
    gate_result = cicd_gate_check(report["findings"])
    print(f"\n배포 가능 여부: {'✅ PASS' if gate_result['pass'] else '❌ BLOCKED'}")
    print(f"차단 사유: {gate_result['summary']}")
