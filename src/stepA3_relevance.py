"""
Track A / Step A3 — biological relevance re-scoring.

Uses:
  - disease evidence (association_score)
  - literature support (literature_max_rag_score)
  - tissue relevance heuristic (snippet mention vs input tissue)
  - subtype relevance heuristic (snippet mention vs input subtype)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src.lib.http_client import make_http_client

from src.lib.paths import manifest_path, run_dir
from src.lib.run_manifest import read_manifest
from src.lib.settings import load_config
from src.lib.tissue_filter import combined_tissue_score
from src.lib.track_a.paths import step_a2_path, step_a3_path
from src.lib.track_a.scoring import minmax, safe_float, weighted_sum


def _infer_text_relevance(text: str, keyword: str | None) -> float:
    if not keyword:
        return 0.5
    t = (text or "").lower()
    k = keyword.strip().lower()
    if not k:
        return 0.5
    return 1.0 if k in t else 0.3


def run_step_a3(run_id: str) -> Path:
    in_path = step_a2_path(run_id)
    if not in_path.is_file():
        raise FileNotFoundError(f"Run A2 first. Missing: {in_path}")

    merged_path = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    if not merged_path.is_file():
        raise FileNotFoundError(f"Missing merged targets from step2: {merged_path}")

    m = read_manifest(manifest_path(run_id))
    tissue = m.input.tissue
    subtype = m.input.disease_subtype

    a2 = pd.read_csv(in_path)
    base = pd.read_csv(merged_path)
    base = base[
        [
            "gene_symbol",
            "ensembl_gene_id",
            "literature_max_rag_score",
            "literature_snippet",
            "association_score",
        ]
    ].copy()
    base = base.drop_duplicates(subset=["ensembl_gene_id", "gene_symbol"], keep="first")

    df = a2.merge(
        base,
        on=["gene_symbol", "ensembl_gene_id"],
        how="left",
        suffixes=("", "_base"),
    )
    if "association_score_base" in df.columns:
        df["association_score"] = df["association_score"].fillna(df["association_score_base"])
        df = df.drop(columns=["association_score_base"], errors="ignore")

    lit_raw = [safe_float(x, 0.0) for x in df["literature_max_rag_score"].fillna(0.0).tolist()]
    db_raw = [safe_float(x, 0.0) for x in df["association_score"].fillna(0.0).tolist()]
    df["literature_support_norm"] = minmax(lit_raw)
    df["disease_evidence_norm"] = minmax(db_raw)

    tissue_scores = []
    subtype_scores = []
    tcfg = load_config().tissue_filter
    disease = m.input.disease_label

    with make_http_client() as client:
        for pos, (_, r) in enumerate(df.iterrows()):
            snippet = str(r.get("literature_snippet") or "")
            subtype_scores.append(_infer_text_relevance(snippet, subtype))
            if tcfg.enabled and tissue:
                detail = combined_tissue_score(
                    snippet=snippet,
                    gene_symbol=str(r.get("gene_symbol") or ""),
                    disease=disease,
                    tissue=tissue,
                    client=client if pos < tcfg.max_genes_for_epmc else None,
                    weights=tcfg.weights,
                )
                tissue_scores.append(detail["tissue_relevance_score"])
            else:
                tissue_scores.append(_infer_text_relevance(snippet, tissue))
    df["tissue_relevance_score"] = tissue_scores
    df["subtype_relevance_score"] = subtype_scores

    br_scores = []
    for _, r in df.iterrows():
        br_scores.append(
            weighted_sum(
                {
                    "disease_evidence": safe_float(r["disease_evidence_norm"]),
                    "literature_support": safe_float(r["literature_support_norm"]),
                    "tissue_relevance": safe_float(r["tissue_relevance_score"]),
                    "subtype_relevance": safe_float(r["subtype_relevance_score"]),
                },
                {
                    "disease_evidence": 0.45,
                    "literature_support": 0.20,
                    "tissue_relevance": 0.20,
                    "subtype_relevance": 0.15,
                },
            )
        )
    df["biological_relevance_score"] = br_scores
    df = df.sort_values("biological_relevance_score", ascending=False)

    out_path = step_a3_path(run_id)
    df.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(df)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track A Step A3 — biological relevance re-scoring")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_a3(args.run_id)


if __name__ == "__main__":
    main()
