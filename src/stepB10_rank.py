"""
Track B / B10 — final novel candidate ranking.
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
from src.lib.track_b.paths import (
    step_b10_path,
    step_b2_path,
    step_b3_path,
    step_b4_path,
    step_b5_path,
    step_b6_path,
    step_b7_path,
    step_b8_path,
    step_b9_path,
)
from src.lib.track_b.scoring import minmax, safe_float, weighted_sum


def run_step_b10(run_id: str) -> Path:
    req = [
        step_b2_path(run_id),
        step_b3_path(run_id),
        step_b4_path(run_id),
        step_b5_path(run_id),
        step_b6_path(run_id),
        step_b7_path(run_id),
        step_b8_path(run_id),
        step_b9_path(run_id),
    ]
    for p in req:
        if not p.is_file():
            raise FileNotFoundError(f"Missing prerequisite file: {p}")

    cfg = load_config()
    manifest = read_manifest(manifest_path(run_id))
    tissue = manifest.input.tissue
    disease = manifest.input.disease_label
    known_path = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    known = pd.read_csv(known_path) if known_path.is_file() else pd.DataFrame()
    snippet_map = {}
    if not known.empty and "gene_symbol" in known.columns:
        for _, row in known.iterrows():
            sym = str(row.get("gene_symbol") or "").upper()
            if sym:
                snippet_map[sym] = str(row.get("literature_snippet") or "")

    base = _scores(step_b2_path(run_id), ["functional_similarity_score"])
    b3 = _scores(step_b3_path(run_id), ["coexpression_proxy_score"])
    b4 = _scores(step_b4_path(run_id), ["differential_expression_score"])
    b5 = _scores(step_b5_path(run_id), ["pathway_relevance_score"])
    b6 = _scores(step_b6_path(run_id), ["genetic_support_score"])
    b7 = _scores(step_b7_path(run_id), ["network_prioritization_score"])
    b8 = _scores(step_b8_path(run_id), ["novelty_score"])
    b9 = _scores(step_b9_path(run_id), ["b9_readiness_score"])

    df = base.merge(b3, on="candidate_gene_symbol", how="left")
    df = df.merge(b4, on="candidate_gene_symbol", how="left")
    df = df.merge(b5, on="candidate_gene_symbol", how="left")
    df = df.merge(b6, on="candidate_gene_symbol", how="left")
    df = df.merge(b7, on="candidate_gene_symbol", how="left")
    df = df.merge(b8, on="candidate_gene_symbol", how="left")
    df = df.merge(b9, on="candidate_gene_symbol", how="left")
    df = df.fillna(0.0)
    # Raw Jaccard against every known gene is tiny. Scale it across this
    # candidate list so the closest functional match can affect the rank.
    df["functional_similarity_score"] = minmax(
        [safe_float(value) for value in df["functional_similarity_score"].tolist()]
    )

    tissue_scores: list[float] = []
    tcfg = cfg.tissue_filter
    with make_http_client() as client:
        for pos, (_, r) in enumerate(df.iterrows()):
            gene = str(r["candidate_gene_symbol"] or "")
            snippet = snippet_map.get(gene.upper(), "")
            if tcfg.enabled and tissue:
                detail = combined_tissue_score(
                    snippet=snippet,
                    gene_symbol=gene,
                    disease=disease,
                    tissue=tissue,
                    client=client if pos < tcfg.max_genes_for_epmc else None,
                    weights=tcfg.weights,
                )
                tissue_scores.append(detail["tissue_relevance_score"])
            else:
                tissue_scores.append(0.5)
    df["tissue_relevance_score"] = tissue_scores

    w = cfg.track_b.final_ranking_weights
    finals = []
    reasons = []
    for _, r in df.iterrows():
        parts = {
            "network_support": safe_float(r["network_prioritization_score"]),
            "pathway_relevance": safe_float(r["pathway_relevance_score"]),
            "expression_evidence": safe_float(r["differential_expression_score"]),
            "coexpression": safe_float(r["coexpression_proxy_score"]),
            "functional_similarity": safe_float(r["functional_similarity_score"]),
            "genetic_support": safe_float(r["genetic_support_score"]),
            "literature_weak_support": safe_float(r["novelty_score"]),
            "druggability": safe_float(r["b9_readiness_score"]),
            "tissue_relevance": safe_float(r["tissue_relevance_score"]),
        }
        final = weighted_sum(parts, w)
        finals.append(final)
        reasons.append(
            "net={:.3f}; path={:.3f}; expr={:.3f}; coexp={:.3f}; func={:.3f}; genetic={:.3f}; novelty={:.3f}; drug={:.3f}; tissue={:.3f}".format(
                parts["network_support"],
                parts["pathway_relevance"],
                parts["expression_evidence"],
                parts["coexpression"],
                parts["functional_similarity"],
                parts["genetic_support"],
                parts["literature_weak_support"],
                parts["druggability"],
                parts["tissue_relevance"],
            )
        )
    df["final_novel_score"] = finals
    df["selection_reason"] = reasons
    df = df.sort_values("final_novel_score", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1

    out_cols = [
        "rank",
        "candidate_gene_symbol",
        "final_novel_score",
        "network_prioritization_score",
        "pathway_relevance_score",
        "differential_expression_score",
        "coexpression_proxy_score",
        "novelty_score",
        "b9_readiness_score",
        "tissue_relevance_score",
        "functional_similarity_score",
        "genetic_support_score",
        "selection_reason",
    ]
    out = df[out_cols]
    out_path = step_b10_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def _scores(path: Path, columns: list[str]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    keep = ["candidate_gene_symbol", *columns]
    missing = [column for column in keep if column not in frame.columns]
    if missing:
        raise ValueError(f"{path.name} is missing {', '.join(missing)}")
    out = frame[keep].copy()
    out["candidate_gene_symbol"] = out["candidate_gene_symbol"].astype(str).str.strip().str.upper()
    out = out[out["candidate_gene_symbol"] != ""]
    return out.drop_duplicates(subset=["candidate_gene_symbol"], keep="first")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B10 — final ranking")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b10(args.run_id)


if __name__ == "__main__":
    main()
