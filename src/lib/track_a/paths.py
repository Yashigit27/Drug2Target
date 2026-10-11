from __future__ import annotations

from pathlib import Path

from src.lib.paths import run_dir


def track_a_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "artifacts" / "track_a"
    d.mkdir(parents=True, exist_ok=True)
    return d


def step_a1_path(run_id: str) -> Path:
    return track_a_dir(run_id) / "stepA1_saturation.csv"


def step_a2_path(run_id: str) -> Path:
    return track_a_dir(run_id) / "stepA2_downweighted.csv"


def step_a3_path(run_id: str) -> Path:
    return track_a_dir(run_id) / "stepA3_relevance.csv"


def step_a4_path(run_id: str) -> Path:
    return track_a_dir(run_id) / "stepA4_cadd_readiness.csv"


def step_a5_path(run_id: str) -> Path:
    return track_a_dir(run_id) / "ranked_known_targets.csv"
