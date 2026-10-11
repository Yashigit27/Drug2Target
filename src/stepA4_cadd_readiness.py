"""
Track A / Step A4 — CADD readiness analysis.

Uses tractability-derived signals from A1 output to estimate:
  - structure availability
  - pocketability / ligand precedent
  - class-level tractability proxy
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.track_a.paths import step_a1_path, step_a4_path
from src.lib.track_a.scoring import safe_float, weighted_sum


def run_step_a4(run_id: str) -> Path:
    in_path = step_a1_path(run_id)
    if not in_path.is_file():
        raise FileNotFoundError(f"Run A1 first. Missing: {in_path}")

    df = pd.read_csv(in_path)
    if df.empty:
        raise ValueError("A1 output is empty")

    # Proxy columns assembled from A1 target profile extraction.
    df["structure_with_ligand_flag"] = df["ligand_flag"].fillna(0).astype(float)
    df["swissprot_flag"] = (df["uniprot_swissprot_count"].fillna(0) > 0).astype(float)
    df["druggable_family_flag"] = (df["ligand_flag"].fillna(0) > 0).astype(float)
    df["pocketability_flag"] = df["ligand_flag"].fillna(0).astype(float)
    df["ligand_precedent_flag"] = df["approved_drug_flag"].fillna(0).astype(float)

    scores = []
    for _, r in df.iterrows():
        scores.append(
            weighted_sum(
                {
                    "structure_with_ligand": safe_float(r["structure_with_ligand_flag"]),
                    "pocketability": safe_float(r["pocketability_flag"]),
                    "ligand_precedent": safe_float(r["ligand_precedent_flag"]),
                    "swissprot": safe_float(r["swissprot_flag"]),
                    "druggable_family": safe_float(r["druggable_family_flag"]),
                },
                {
                    "structure_with_ligand": 0.35,
                    "pocketability": 0.25,
                    "ligand_precedent": 0.20,
                    "swissprot": 0.10,
                    "druggable_family": 0.10,
                },
            )
        )
    out = df[
        [
            "gene_symbol",
            "ensembl_gene_id",
            "structure_with_ligand_flag",
            "pocketability_flag",
            "ligand_precedent_flag",
            "swissprot_flag",
            "druggable_family_flag",
        ]
    ].copy()
    out["cadd_readiness_score"] = scores
    out = out.sort_values("cadd_readiness_score", ascending=False)

    out_path = step_a4_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track A Step A4 — CADD readiness")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_a4(args.run_id)


if __name__ == "__main__":
    main()
