"""
Track A / Step A5 — final ranking for underexplored known targets.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.settings import load_config
from src.lib.track_a.paths import step_a2_path, step_a3_path, step_a4_path, step_a5_path
from src.lib.track_a.scoring import safe_float, weighted_sum


def run_step_a5(run_id: str) -> Path:
    p2 = step_a2_path(run_id)
    p3 = step_a3_path(run_id)
    p4 = step_a4_path(run_id)
    for p in (p2, p3, p4):
        if not p.is_file():
            raise FileNotFoundError(f"Missing prerequisite file: {p}")

    a2 = pd.read_csv(p2)
    a3 = pd.read_csv(p3)
    a4 = pd.read_csv(p4)

    df = a2.merge(
        a3[
            [
                "gene_symbol",
                "ensembl_gene_id",
                "biological_relevance_score",
                "tissue_relevance_score",
            ]
        ],
        on=["gene_symbol", "ensembl_gene_id"],
        how="left",
    ).merge(
        a4[["gene_symbol", "ensembl_gene_id", "cadd_readiness_score"]],
        on=["gene_symbol", "ensembl_gene_id"],
        how="left",
    )

    df["low_crowdedness_score"] = 1.0 - df["crowded_score"].fillna(0.0)
    df["tissue_relevance_score"] = df["tissue_relevance_score"].fillna(0.5)
    df["biological_relevance_score"] = df["biological_relevance_score"].fillna(0.0)
    df["cadd_readiness_score"] = df["cadd_readiness_score"].fillna(0.0)

    w = load_config().track_a.final_ranking_weights
    finals = []
    reasons = []
    for _, r in df.iterrows():
        comp = {
            "biological_relevance": safe_float(r["biological_relevance_score"]),
            "cadd_readiness": safe_float(r["cadd_readiness_score"]),
            "tissue_relevance": safe_float(r["tissue_relevance_score"]),
            "low_crowdedness": safe_float(r["low_crowdedness_score"]),
        }
        final = weighted_sum(comp, w)
        finals.append(final)
        reasons.append(
            "bio={:.3f}; cadd={:.3f}; tissue={:.3f}; low_crowd={:.3f}".format(
                comp["biological_relevance"],
                comp["cadd_readiness"],
                comp["tissue_relevance"],
                comp["low_crowdedness"],
            )
        )
    df["final_known_track_a_score"] = finals
    df["selection_reason"] = reasons
    df = df.sort_values("final_known_track_a_score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    out_cols = [
        "rank",
        "gene_symbol",
        "ensembl_gene_id",
        "final_known_track_a_score",
        "biological_relevance_score",
        "cadd_readiness_score",
        "tissue_relevance_score",
        "low_crowdedness_score",
        "crowded_score",
        "crowded_action",
        "publication_count",
        "approved_drug_flag",
        "clinical_flag",
        "ligand_flag",
        "selection_reason",
    ]
    out_cols = [c for c in out_cols if c in df.columns]
    out = df[out_cols].copy()

    out_path = step_a5_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track A Step A5 — final ranking")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_a5(args.run_id)


if __name__ == "__main__":
    main()
