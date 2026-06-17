"""Domain types for the FSI-Mythos pipeline.

Pure data — no AWS or Bedrock imports here, so the whole domain layer is unit-testable
without network or heavy dependencies.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import List, Optional, Tuple


def enforce_budget(files, max_files: int, max_bytes: int):
    """Cost-DoS guard: keep files (caller pre-orders by risk) until a file-count or total-byte
    cap is hit. Returns ``(kept, dropped_count)`` where kept is ``[(path, size), ...]``."""
    kept = []
    total = 0
    for path, size in files:
        if len(kept) >= max_files:
            break  # file-count cap reached — nothing more fits
        if total + size > max_bytes:
            continue  # this file is too big; keep trying smaller, higher-risk ones
        kept.append((path, size))
        total += size
    return kept, len(files) - len(kept)

# Default per-role Claude models. These are the cross-region inference profiles actually
# available for Opus in the target account/region (global.* — verified via
# list-inference-profiles). agents.models leaves an already-prefixed id untouched, and
# falls back to the region prefix (apac.*/us.*) for bare ids. Override via env if needed.
DEFAULT_HUNTER_MODEL = "global.anthropic.claude-opus-4-7"
DEFAULT_CHALLENGER_MODEL = "global.anthropic.claude-opus-4-6-v1"
DEFAULT_VALIDATOR_MODEL = "global.anthropic.claude-opus-4-8"
DEFAULT_RANKER_MODEL = "global.anthropic.claude-opus-4-6-v1"


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

    # Cost-DoS guards: hard ceilings on how much a single scan will process.
    max_total_files: int = 200
    max_total_bytes: int = 5 * 1024 * 1024  # 5 MiB

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
