"""
Track B / B6 — Genetic support.

Uses overlap with disease-association evidence from merged step2 file.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.paths import run_dir
from src.lib.track_b.paths import step_b1_path, step_b6_path
from src.lib.track_b.scoring import minmax


def run_step_b6(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    cands = pd.read_csv(p1)["candidate_gene_symbol"].dropna().astype(str).str.upper().tolist()

    merged = pd.read_csv(run_dir(run_id) / "artifacts" / "known_disease_genes.csv")
    merged["gene_symbol_up"] = merged["gene_symbol"].astype(str).str.upper()
    assoc_map = (
        merged.groupby("gene_symbol_up", as_index=False)["association_score"].max().set_index("gene_symbol_up")[
            "association_score"
        ]
    )

    recs = []
    for c in cands:
        raw = float(assoc_map.get(c, 0.0) or 0.0)
        recs.append({"candidate_gene_symbol": c, "genetic_support_raw": raw})
    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    out["genetic_support_score"] = minmax(out["genetic_support_raw"].tolist())
    out = out.sort_values("genetic_support_score", ascending=False)
    out_path = step_b6_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B6 — genetic support")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b6(args.run_id)


if __name__ == "__main__":
    main()
