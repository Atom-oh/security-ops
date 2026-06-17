"""Phase 1 — sink-guided slicing.

Rather than match every line, we locate calls to known dangerous *sinks* and extract a
context window around each. Downstream agents reason over these slices instead of whole
files, which keeps token cost down and focuses the hunt on tainted-data destinations.
"""
from __future__ import annotations

from typing import Dict, List

from pipeline.config import Language

# Per-language sink tokens (substring match on a stripped line). Ordered longest-first
# within a language so "os.system" wins over a bare "system".
SINKS: Dict[Language, List[str]] = {
    Language.C: [
        "strcpy", "strcat", "sprintf", "vsprintf", "gets", "memcpy", "memmove",
        "scanf", "system", "popen", "execve", "execl", "alloca",
    ],
    Language.CPP: [
        "strcpy", "strcat", "sprintf", "vsprintf", "gets", "memcpy", "memmove",
        "scanf", "system", "popen", "execve", "execl",
    ],
    Language.JAVA: [
        "Runtime.getRuntime().exec", "ProcessBuilder", "Statement.execute",
        "ObjectInputStream", "createStatement", "ScriptEngine",
    ],
    Language.PYTHON: [
        "os.system", "os.popen", "subprocess.", "pickle.loads", "yaml.load",
        "eval", "exec", "__import__", "marshal.loads",
    ],
    Language.JAVASCRIPT: [
        "child_process", "exec(", "execSync", "eval", "Function(", "innerHTML",
        "document.write", "dangerouslySetInnerHTML",
    ],
    Language.TYPESCRIPT: [
        "child_process", "exec(", "execSync", "eval", "Function(", "innerHTML",
        "document.write", "dangerouslySetInnerHTML",
    ],
    Language.GO: ["exec.Command", "os/exec", "template.HTML"],
    Language.KOTLIN: ["Runtime.getRuntime().exec", "ProcessBuilder"],
    Language.SWIFT: ["system(", "NSTask", "Process()"],
}


def sink_guided_slice(
    file_path: str, language: Language, context_lines: int = 20
) -> List[dict]:
    """Return slices ``{sink, line, start_line, end_line, context}`` for risky sinks.

    ``line``/``start_line``/``end_line`` are 1-indexed and inclusive. ``context`` is the
    joined source of ``[start_line, end_line]``.
    """
    sinks = SINKS.get(language, [])
    if not sinks:
        return []
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []

    out: List[dict] = []
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        for sink in sinks:
            if sink in stripped:
                lineno = idx + 1  # 1-indexed
                start = max(1, lineno - context_lines)
                end = min(len(lines), lineno + context_lines)
                out.append(
                    {
                        "sink": sink,
                        "line": lineno,
                        "start_line": start,
                        "end_line": end,
                        "context": "\n".join(lines[start - 1 : end]),
                    }
                )
                break  # one slice per line — first (longest) matching sink wins
    return out
