"""
Track B / B5 — Pathway relevance (Reactome + KEGG).

Simple idea:
1. Annotate seed + candidate genes via mygene (Reactome and KEGG IDs).
2. Count how often each pathway appears among disease seeds.
3. Prefer pathways seen in multiple seeds (recurrent = more disease-relevant).
4. Score each candidate by frequency-weighted overlap with those pathways.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import pandas as pd

from src.lib.paths import run_dir
from src.lib.track_b.paths import step_b1_path, step_b5_path
from src.lib.track_b.scoring import minmax
from src.lib.track_b.sources import mygene_annotations, pathway_ids_from_annotation

# Pathway must appear in at least this many seeds to count as disease-relevant.
MIN_SEED_HITS = 2


def run_step_b5(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")

    cands = (
        pd.read_csv(p1)["candidate_gene_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
        .tolist()
    )
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

    # How many seeds carry each pathway ID (Reactome + KEGG).
    seed_pathway_count: Counter[str] = Counter()
    seeds_with_pathways = 0
    for s in seeds:
        paths = pathway_ids_from_annotation(ann.get(s))
        if not paths:
            continue
        seeds_with_pathways += 1
        seed_pathway_count.update(paths)

    if seeds_with_pathways <= 0:
        raise ValueError("B5: no pathway annotations found for seed genes.")

    # Recurrent pathways among seeds (= simple enrichment filter).
    disease_paths = {
        p for p, n in seed_pathway_count.items() if n >= MIN_SEED_HITS
    }
    # Fallback if the filter is too strict for small seed sets.
    if len(disease_paths) < 5:
        disease_paths = set(seed_pathway_count)

    n_seeds = float(seeds_with_pathways)
    raw_scores: list[float] = []
    recs: list[dict] = []

    for c in cands:
        c_paths = pathway_ids_from_annotation(ann.get(c))
        shared = c_paths & disease_paths
        # Frequency-weighted support: pathways shared by more seeds count more.
        raw = sum(seed_pathway_count[p] for p in shared) / n_seeds
        raw_scores.append(raw)
        recs.append(
            {
                "candidate_gene_symbol": c,
                "candidate_pathway_count": len(c_paths),
                "pathway_overlap_count": len(shared),
                "pathway_support_raw": round(raw, 6),
            }
        )

    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    out["pathway_relevance_score"] = minmax(out["pathway_support_raw"].tolist())
    out = out.sort_values("pathway_relevance_score", ascending=False)

    out_path = step_b5_path(run_id)
    out.to_csv(out_path, index=False)
    print(
        f"B5: seeds_with_pathways={seeds_with_pathways} "
        f"disease_pathways={len(disease_paths)} "
        f"candidates_with_pathways={int((out['candidate_pathway_count'] > 0).sum())}/{len(out)}"
    )
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B5 — pathway relevance")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b5(args.run_id)


if __name__ == "__main__":
    main()
