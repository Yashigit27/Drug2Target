from __future__ import annotations

from pathlib import Path

from src.lib.paths import run_dir


def track_b_dir(run_id: str) -> Path:
    d = run_dir(run_id) / "artifacts" / "track_b"
    d.mkdir(parents=True, exist_ok=True)
    return d


def step_b1_edges_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB1_network_edges.csv"


def step_b1_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB1_candidate_neighbors.csv"


def step_b2_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB2_functional_similarity.csv"


def step_b3_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB3_coexpression.csv"


def step_b4_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB4_differential_expression.csv"


def step_b5_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB5_pathway_enrichment.csv"


def step_b6_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB6_genetic_support.csv"


def step_b7_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB7_network_prioritization.csv"


def step_b8_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB8_novelty.csv"


def step_b9_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "stepB9_safety_druggability.csv"


def step_b10_path(run_id: str) -> Path:
    return track_b_dir(run_id) / "ranked_novel_candidates.csv"
