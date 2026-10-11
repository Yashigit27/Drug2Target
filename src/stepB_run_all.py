"""
Track B runner — executes B1 -> B10 in sequence.
"""

from __future__ import annotations

import argparse

from src.stepB10_rank import run_step_b10
from src.stepB1_seed_expansion import run_step_b1
from src.stepB2_functional_similarity import run_step_b2
from src.stepB3_coexpression import run_step_b3
from src.stepB4_differential_expression import run_step_b4
from src.stepB5_pathway import run_step_b5
from src.stepB6_genetic_support import run_step_b6
from src.stepB7_network_prioritization import run_step_b7
from src.stepB8_novelty import run_step_b8
from src.stepB9_safety_druggability import run_step_b9


def run_track_b(run_id: str) -> None:
    run_step_b1(run_id)
    run_step_b2(run_id)
    run_step_b3(run_id)
    run_step_b4(run_id)
    run_step_b5(run_id)
    run_step_b6(run_id)
    run_step_b7(run_id)
    run_step_b8(run_id)
    run_step_b9(run_id)
    run_step_b10(run_id)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run Track B steps B1..B10")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_track_b(args.run_id)


if __name__ == "__main__":
    main()
