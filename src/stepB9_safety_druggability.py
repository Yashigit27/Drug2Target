"""
Track B / B9 — safety + druggability + structure proxy.

For candidates without stable ensembl id mapping, uses conservative defaults.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.track_b.paths import step_b1_path, step_b9_path


def run_step_b9(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    out = b1[["candidate_gene_symbol"]].drop_duplicates().copy()
    # Conservative baseline; stronger tractability mapping can be added when ensembl ids are integrated.
    out["structure_availability_score"] = 0.4
    out["druggability_score"] = 0.4
    out["safety_score"] = 0.5
    out["b9_readiness_score"] = 0.4 * out["structure_availability_score"] + 0.4 * out[
        "druggability_score"
    ] + 0.2 * out["safety_score"]
    out_path = step_b9_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B9 — safety/druggability/structure")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b9(args.run_id)


if __name__ == "__main__":
    main()
