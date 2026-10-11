"""
Track A / Step A2 — downweight overworked targets.

Input:
  outputs/<run_id>/artifacts/track_a/stepA1_saturation.csv

Output:
  outputs/<run_id>/artifacts/track_a/stepA2_downweighted.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.settings import load_config
from src.lib.track_a.paths import step_a1_path, step_a2_path


def run_step_a2(run_id: str) -> Path:
    cfg = load_config().track_a
    in_path = step_a1_path(run_id)
    if not in_path.is_file():
        raise FileNotFoundError(f"Run A1 first. Missing: {in_path}")

    df = pd.read_csv(in_path)
    if df.empty or "crowded_score" not in df.columns:
        raise ValueError("A1 output is empty or missing crowded_score")

    q_hi = float(df["crowded_score"].quantile(cfg.crowded_high_quantile))
    q_ext = float(df["crowded_score"].quantile(cfg.crowded_extreme_quantile))

    penalties: list[float] = []
    actions: list[str] = []
    for _, r in df.iterrows():
        c = float(r["crowded_score"])
        if c >= q_ext:
            penalties.append(0.50)
            actions.append("strong_downweight")
        elif c >= q_hi:
            penalties.append(0.75)
            actions.append("moderate_downweight")
        else:
            penalties.append(1.00)
            actions.append("keep")

    df["crowded_penalty"] = penalties
    df["crowded_action"] = actions
    df["downweighted_association_score"] = df["association_score"].fillna(0.0) * df[
        "crowded_penalty"
    ]
    df = df.sort_values("downweighted_association_score", ascending=False)

    out_path = step_a2_path(run_id)
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(df)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track A Step A2 — downweight crowded targets")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_a2(args.run_id)


if __name__ == "__main__":
    main()
