"""
Track A runner — executes A1 -> A5 in sequence.
"""

from __future__ import annotations

import argparse

from src.stepA1_saturation import run_step_a1
from src.stepA2_downweight import run_step_a2
from src.stepA3_relevance import run_step_a3
from src.stepA4_cadd_readiness import run_step_a4
from src.stepA5_rank import run_step_a5


def run_track_a(run_id: str) -> None:
    run_step_a1(run_id)
    run_step_a2(run_id)
    run_step_a3(run_id)
    run_step_a4(run_id)
    run_step_a5(run_id)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Run Track A steps A1..A5")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_track_a(args.run_id)


if __name__ == "__main__":
    main()
