from __future__ import annotations

from pathlib import Path

from src.lib.paths import run_dir


def fusion_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "artifacts" / "fusion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def step_f1_portfolio_path(run_id: str) -> Path:
    return fusion_dir(run_id) / "unified_target_portfolio.csv"


def step_f1_summary_path(run_id: str) -> Path:
    return fusion_dir(run_id) / "fusion_summary.json"
