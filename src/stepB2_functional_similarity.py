"""
Track B / B2 — Functional similarity (GO/pathway/domain overlap via mygene).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.paths import run_dir
from src.lib.track_b.paths import step_b1_path, step_b2_path
from src.lib.track_b.scoring import weighted_sum
from src.lib.track_b.sources import extract_id_set, mygene_annotations


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    u = a | b
    if not u:
        return 0.0
    return len(a & b) / len(u)


def run_step_b2(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")

    merged = pd.read_csv(run_dir(run_id) / "artifacts" / "known_disease_genes.csv")
    seeds = (
        merged[merged["association_score"].notna()]["gene_symbol"]
        .dropna()
        .astype(str)
        .str.upper()
        .unique()
        .tolist()
    )
    cands = pd.read_csv(p1)["candidate_gene_symbol"].dropna().astype(str).str.upper().tolist()

    ann = mygene_annotations(sorted(set(seeds + cands)))

    seed_go, seed_path, seed_dom = set(), set(), set()
    for s in seeds:
        row = ann.get(s)
        if not row:
            continue
        seed_go |= extract_id_set(row.get("go"), "id")
        seed_path |= extract_id_set(row.get("pathway"), "id")
        seed_dom |= extract_id_set(row.get("interpro"), "id")

    recs = []
    for c in cands:
        row = ann.get(c, {})
        c_go = extract_id_set(row.get("go"), "id")
        c_path = extract_id_set(row.get("pathway"), "id")
        c_dom = extract_id_set(row.get("interpro"), "id")
        go_j = _jaccard(c_go, seed_go)
        path_j = _jaccard(c_path, seed_path)
        dom_j = _jaccard(c_dom, seed_dom)
        score = weighted_sum(
            {"go": go_j, "pathway": path_j, "domain": dom_j},
            {"go": 0.4, "pathway": 0.4, "domain": 0.2},
        )
        recs.append(
            {
                "candidate_gene_symbol": c,
                "go_similarity": go_j,
                "pathway_overlap_score": path_j,
                "domain_similarity": dom_j,
                "functional_similarity_score": score,
            }
        )

    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    out = out.sort_values("functional_similarity_score", ascending=False)
    out_path = step_b2_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B2 — functional similarity")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b2(args.run_id)


if __name__ == "__main__":
    main()
