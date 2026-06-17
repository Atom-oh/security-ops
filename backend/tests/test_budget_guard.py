"""Tests for the scan budget guard (cost-DoS protection)."""
from __future__ import annotations

from pipeline.config import ScanConfig, enforce_budget


def test_under_budget_keeps_all():
    files = [("a.py", 100), ("b.py", 200)]
    kept, dropped = enforce_budget(files, max_files=10, max_bytes=10_000)
    assert [k for k, _ in kept] == ["a.py", "b.py"]
    assert dropped == 0


def test_file_count_cap():
    files = [(f"f{i}.py", 10) for i in range(10)]
    kept, dropped = enforce_budget(files, max_files=3, max_bytes=10_000)
    assert len(kept) == 3
    assert dropped == 7


def test_byte_cap_stops_accumulation():
    files = [("big1", 600), ("big2", 600), ("big3", 600)]
    kept, dropped = enforce_budget(files, max_files=100, max_bytes=1000)
    # 600 + 600 = 1200 > 1000 → only first fits
    assert len(kept) == 1
    assert dropped == 2


def test_config_has_budget_defaults():
    cfg = ScanConfig(project_path="/x")
    assert cfg.max_total_files > 0
    assert cfg.max_total_bytes > 0
