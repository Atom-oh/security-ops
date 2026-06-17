"""Domain types for the FSI-Mythos pipeline.

Pure data — no AWS or Bedrock imports here, so the whole domain layer is unit-testable
without network or heavy dependencies.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

# Default per-role Claude model *logical* names. The region-aware inference-profile
# prefix (apac.* / us.*) is resolved in agents.models — these are the bare ids.
DEFAULT_HUNTER_MODEL = "anthropic.claude-opus-4-7-20260415-v1:0"
DEFAULT_CHALLENGER_MODEL = "anthropic.claude-opus-4-6-20260205-v1:0"
DEFAULT_VALIDATOR_MODEL = "anthropic.claude-opus-4-8-20260601-v1:0"
DEFAULT_RANKER_MODEL = "anthropic.claude-opus-4-6-20260205-v1:0"


class Severity(str, Enum):
    """Finding severity. ``str`` base keeps JSON/ASFF serialization trivial."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def weight(self) -> int:
        return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}[self.value]


class Verdict(str, Enum):
    """Validator verdict (Phase 4)."""

    CONFIRMED = "confirmed"
    LIKELY = "likely"
    DISMISSED = "dismissed"
    ESCALATE = "escalate"


class Language(str, Enum):
    """Source languages the pipeline understands."""

    C = "c"
    CPP = "cpp"
    JAVA = "java"
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    KOTLIN = "kotlin"
    SWIFT = "swift"
    GO = "go"

    @classmethod
    def from_extension(cls, ext: str) -> Optional["Language"]:
        return _EXTENSION_MAP.get(ext.lower())


_EXTENSION_MAP = {
    ".c": Language.C,
    ".h": Language.C,
    ".cpp": Language.CPP,
    ".cc": Language.CPP,
    ".cxx": Language.CPP,
    ".hpp": Language.CPP,
    ".java": Language.JAVA,
    ".py": Language.PYTHON,
    ".js": Language.JAVASCRIPT,
    ".jsx": Language.JAVASCRIPT,
    ".ts": Language.TYPESCRIPT,
    ".tsx": Language.TYPESCRIPT,
    ".kt": Language.KOTLIN,
    ".swift": Language.SWIFT,
    ".go": Language.GO,
}


@dataclass
class ScanConfig:
    """Configuration for one scan run."""

    project_path: str
    max_files: int = 8
    pass_at_k: int = 1
    region: str = "ap-northeast-2"

    hunter_model: str = DEFAULT_HUNTER_MODEL
    challenger_model: str = DEFAULT_CHALLENGER_MODEL
    validator_model: str = DEFAULT_VALIDATOR_MODEL
    ranker_model: str = DEFAULT_RANKER_MODEL

    max_tokens: int = 16384
    thinking_effort: str = "high"  # output_config.effort for adaptive thinking
    temperature: float = 1.0  # Anthropic recommends 1.0 with extended thinking

    sandbox_enabled: bool = False

    # FSI specialization
    fsi_mode: bool = True
    scan_scope: str = "defensive"  # defensive | full
    compliance_tags: List[str] = field(
        default_factory=lambda: ["K-ISMS", "전자금융감독규정"]
    )


@dataclass
class Finding:
    """A single (candidate) vulnerability finding."""

    title: str
    file_path: str
    line_range: Tuple[int, int]
    severity: Severity
    cwe_id: Optional[str] = None
    description: str = ""
    exploitation_scenario: str = ""
    patch_suggestion: str = ""
    confidence: float = 0.0  # 0..1, set after validation
    chain_potential: bool = False
    verdict: Optional[Verdict] = None
    validated: bool = False
    id: str = field(default="", init=True)

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.make_id(self.file_path, self.line_range, self.title)

    @staticmethod
    def make_id(file_path: str, line_range: Tuple[int, int], title: str) -> str:
        """Stable identity from *location + title* (severity/verdict excluded)."""
        key = f"{file_path}:{line_range[0]}-{line_range[1]}:{title}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return f"fsi-{digest}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = self.severity.value if self.severity else None
        d["verdict"] = self.verdict.value if self.verdict else None
        d["line_range"] = list(self.line_range)
        return d
