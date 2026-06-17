"""Phase 0 — language detection.

Walk the target tree, map files to languages by extension, and skip dependency /
VCS / build directories so we never burn budget on third-party code.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, List

from pipeline.config import Language

EXCLUDE_DIRS = {".git", "node_modules", "vendor", "build", "dist", ".venv", "__pycache__"}


def detect_languages(project_path: str) -> Dict[Language, List[str]]:
    """Return ``{Language: [absolute file paths]}`` for recognized source files."""
    result: Dict[Language, List[str]] = {}
    for root, dirs, files in os.walk(project_path):
        # prune excluded directories in place
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            lang = Language.from_extension(Path(name).suffix)
            if lang is None:
                continue
            result.setdefault(lang, []).append(os.path.join(root, name))
    return result
