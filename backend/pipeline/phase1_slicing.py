"""Phase 1 — sink-guided slicing.

Rather than match every line, we locate calls to known dangerous *sinks* and extract a
context window around each. Downstream agents reason over these slices instead of whole
files, which keeps token cost down and focuses the hunt on tainted-data destinations.
"""
from __future__ import annotations

import re
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


def _matches(sink: str, line: str) -> bool:
    """Match a sink in a line.

    Bare identifiers (``strcpy``, ``system``, ``eval``) use a word boundary so a variable
    like ``user_strcpy`` is not a false hit. Tokens containing punctuation (``os.system``,
    ``exec(``) fall back to substring matching.
    """
    if re.fullmatch(r"\w+", sink):
        return re.search(rf"\b{re.escape(sink)}\b", line) is not None
    return sink in line


def _numbered(lines: List[str], start: int, end: int) -> str:
    """Render ``[start, end]`` (1-indexed) with absolute line-number gutters so the Hunter
    reports *file* line numbers, not slice-relative ones."""
    return "\n".join(f"{n:>5}: {lines[n - 1]}" for n in range(start, end + 1))


def numbered_file(file_path: str, max_lines: int = 400) -> str:
    """Read a whole file with absolute line-number gutters (capped) — used as the Hunter
    context for files that had no explicit sink slice, so the LLM can still reason over them."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ""
    clipped = lines[:max_lines]
    body = "\n".join(f"{i + 1:>5}: {line}" for i, line in enumerate(clipped))
    if len(lines) > max_lines:
        body += f"\n... ({len(lines) - max_lines} more lines truncated)"
    return body


def sink_guided_slice(
    file_path: str, language: Language, context_lines: int = 20
) -> List[dict]:
    """Return slices ``{sink, line, start_line, end_line, context, numbered_context}``.

    ``line``/``start_line``/``end_line`` are 1-indexed and inclusive. ``context`` is the raw
    source of ``[start_line, end_line]``; ``numbered_context`` is the same with absolute
    line-number gutters (fed to the Hunter so it returns real file line numbers).
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
            if _matches(sink, stripped):
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
                        "numbered_context": _numbered(lines, start, end),
                    }
                )
                break  # one slice per line — first (longest) matching sink wins
    return out
