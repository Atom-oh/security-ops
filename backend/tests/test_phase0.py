"""Tests for Phase 0 — language detection."""
from __future__ import annotations

from pathlib import Path

from pipeline.config import Language
from pipeline.phase0_languages import detect_languages


def _write(p: Path, rel: str, content: str = "x") -> None:
    f = p / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


def test_detect_basic_mapping(tmp_path: Path):
    _write(tmp_path, "src/transfer.c")
    _write(tmp_path, "src/auth.py")
    _write(tmp_path, "web/app.ts")
    result = detect_languages(str(tmp_path))
    assert Language.C in result
    assert Language.PYTHON in result
    assert Language.TYPESCRIPT in result
    assert any(f.endswith("transfer.c") for f in result[Language.C])


def test_excludes_noise_dirs(tmp_path: Path):
    _write(tmp_path, "keep.py")
    _write(tmp_path, "node_modules/dep/index.js")
    _write(tmp_path, ".git/hooks/pre-commit.py")
    _write(tmp_path, "vendor/lib.c")
    _write(tmp_path, "build/out.c")
    result = detect_languages(str(tmp_path))
    all_files = [f for files in result.values() for f in files]
    assert any(f.endswith("keep.py") for f in all_files)
    assert not any("node_modules" in f for f in all_files)
    assert not any(".git" in f for f in all_files)
    assert not any("vendor" in f for f in all_files)
    assert not any("build" in f for f in all_files)


def test_unknown_extensions_ignored(tmp_path: Path):
    _write(tmp_path, "readme.md")
    _write(tmp_path, "data.json")
    result = detect_languages(str(tmp_path))
    assert result == {}
