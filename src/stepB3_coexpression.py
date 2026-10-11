"""
Track B / B3 — Co-expression support proxy.

Current implementation uses network-neighborhood proxy from B1
until explicit GTEx/GEO matrices are integrated.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.track_b.paths import step_b1_path, step_b3_path
from src.lib.track_b.scoring import minmax


def run_step_b3(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    if b1.empty:
        raise ValueError("B1 output empty")

    seed_norm = minmax(b1["seed_count"].fillna(0.0).astype(float).tolist())
    score_norm = minmax(b1["mean_string_score"].fillna(0.0).astype(float).tolist())
    b1["coexpression_proxy_score"] = [
        0.6 * s + 0.4 * m for s, m in zip(seed_norm, score_norm, strict=False)
    ]

    out = b1[["candidate_gene_symbol", "coexpression_proxy_score"]].copy()
    out = out.sort_values("coexpression_proxy_score", ascending=False)
    out_path = step_b3_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B3 — coexpression proxy")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b3(args.run_id)


if __name__ == "__main__":
    main()
