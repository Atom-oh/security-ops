"""The bundled corpus must be detectable by Phase 0/1."""
from __future__ import annotations

import os

from pipeline.config import Language
from pipeline.phase0_languages import detect_languages
from pipeline.phase1_slicing import sink_guided_slice

CORPUS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sample-target")


def test_languages_detected():
    langs = detect_languages(CORPUS)
    assert Language.C in langs
    assert Language.PYTHON in langs
    assert Language.JAVASCRIPT in langs


def _sinks_in(rel: str, language: Language):
    return {s["sink"] for s in sink_guided_slice(os.path.join(CORPUS, rel), language)}


def test_sink_sinks_present():
    c = _sinks_in("transfer.c", Language.C)
    assert {"strcpy", "sprintf", "system"} <= c
    assert "pickle.loads" in _sinks_in("serial.py", Language.PYTHON)
    assert "innerHTML" in _sinks_in("render.js", Language.JAVASCRIPT)
