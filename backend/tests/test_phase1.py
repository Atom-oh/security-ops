"""Tests for Phase 1 — sink-guided slicing."""
from __future__ import annotations

from pathlib import Path

from pipeline.config import Language
from pipeline.phase1_slicing import sink_guided_slice


def test_finds_c_sinks(tmp_path: Path):
    src = tmp_path / "transfer.c"
    src.write_text(
        "#include <string.h>\n"
        "void f(char *u){\n"
        "  char b[16];\n"
        "  strcpy(b, u);\n"
        "  system(u);\n"
        "}\n"
    )
    slices = sink_guided_slice(str(src), Language.C)
    sinks = {s["sink"] for s in slices}
    assert "strcpy" in sinks
    assert "system" in sinks
    # each slice carries a context window and the line number
    for s in slices:
        assert "context" in s and s["context"]
        assert s["line"] >= 1
        assert s["start_line"] <= s["line"] <= s["end_line"]


def test_finds_python_sinks(tmp_path: Path):
    src = tmp_path / "auth.py"
    src.write_text("import os\n\ndef h(cmd):\n    os.system(cmd)\n    eval(cmd)\n")
    slices = sink_guided_slice(str(src), Language.PYTHON)
    sinks = {s["sink"] for s in slices}
    assert "os.system" in sinks
    assert "eval" in sinks


def test_no_sinks_returns_empty(tmp_path: Path):
    src = tmp_path / "safe.py"
    src.write_text("def add(a, b):\n    return a + b\n")
    assert sink_guided_slice(str(src), Language.PYTHON) == []


def test_context_window_bounded(tmp_path: Path):
    src = tmp_path / "big.c"
    lines = ["int x;"] * 100
    lines[50] = "strcpy(a,b);"
    src.write_text("\n".join(lines) + "\n")
    slices = sink_guided_slice(str(src), Language.C, context_lines=20)
    assert len(slices) == 1
    s = slices[0]
    # ±20 lines around line 51 (1-indexed)
    assert s["start_line"] == 31
    assert s["end_line"] == 71
