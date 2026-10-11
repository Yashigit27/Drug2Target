"""
Track B / B5 — Pathway relevance (Reactome overlap proxy via mygene fields).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.paths import run_dir
from src.lib.track_b.paths import step_b1_path, step_b5_path
from src.lib.track_b.sources import extract_id_set, mygene_annotations


def run_step_b5(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    cands = pd.read_csv(p1)["candidate_gene_symbol"].dropna().astype(str).str.upper().tolist()
    merged = pd.read_csv(run_dir(run_id) / "artifacts" / "known_disease_genes.csv")
    seeds = (
        merged[merged["association_score"].notna()]["gene_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
        .unique()
        .tolist()
    )

    ann = mygene_annotations(sorted(set(cands + seeds)))
    seed_paths = set()
    for s in seeds:
        row = ann.get(s, {})
        seed_paths |= extract_id_set(row.get("pathway"), "id")

    recs = []
    for c in cands:
        row = ann.get(c, {})
        c_paths = extract_id_set(row.get("pathway"), "id")
        overlap = len(c_paths & seed_paths)
        denom = max(1, len(c_paths))
        score = overlap / denom
        recs.append(
            {
                "candidate_gene_symbol": c,
                "candidate_pathway_count": len(c_paths),
                "pathway_overlap_count": overlap,
                "pathway_relevance_score": score,
            }
        )
    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    out = out.sort_values("pathway_relevance_score", ascending=False)
    out_path = step_b5_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B5 — pathway relevance")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b5(args.run_id)


if __name__ == "__main__":
    main()
