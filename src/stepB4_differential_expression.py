"""
Track B / B4 — Differential expression.

Looks up a saved disease-versus-healthy table for this disease and tissue.
When none is saved, Expression Atlas is searched once and the chosen
study is kept. A missing study leaves every candidate neutral.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd

from src.lib.expression.de_contrast import load_contrast, resolve_table_path, score_change
from src.lib.expression.de_select import ensure_contrast
from src.lib.paths import manifest_path
from src.lib.run_manifest import read_manifest
from src.lib.settings import load_config
from src.lib.track_b.paths import step_b1_path, step_b4_path


def run_step_b4(run_id: str) -> Path:
    neighbors = step_b1_path(run_id)
    if not neighbors.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {neighbors}")
    candidates = (
        pd.read_csv(neighbors)["candidate_gene_symbol"].dropna().astype(str).str.strip().tolist()
    )
    seen: set[str] = set()
    genes: list[str] = []
    for gene in candidates:
        key = gene.upper()
        if gene and key not in seen:
            seen.add(key)
            genes.append(gene)
    if not genes:
        raise ValueError("B1 output has no candidate genes")

    manifest = read_manifest(manifest_path(run_id))
    disease_id = manifest.disease_resolution.selected.id
    tissue = manifest.input.tissue
    disease_name = " ".join(
        part
        for part in (
            manifest.disease_resolution.selected.name,
            manifest.input.disease_label,
        )
        if part
    )
    cfg = load_config().track_b.b4
    chosen = ensure_contrast(disease_id, disease_name, tissue, cfg)
    table_path = resolve_table_path(chosen.file) if chosen is not None else None

    if chosen is None or table_path is None or not table_path.is_file():
        out = _neutral(genes)
    else:
        table = load_contrast(table_path, chosen.contrast)
        if not table:
            print(f"B4 {chosen.study} has no readable gene table; scores left neutral")
            out = _neutral(genes)
        else:
            out = _score_genes(genes, table, chosen.study, cfg.min_abs_log2fc, cfg.max_pvalue)
            changed = int((out["de_status"] == "changed").sum())
            print(
                f"B4 {chosen.study} ({table_path.name}): "
                f"{changed} changed, "
                f"{int((out['de_status'] == 'unchanged').sum())} unchanged, "
                f"{int((out['de_status'] == 'not_measured').sum())} not measured"
            )

    out_path = step_b4_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def _neutral(genes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "candidate_gene_symbol": genes,
            "log2_fold_change": math.nan,
            "p_value": math.nan,
            "de_status": "no_contrast",
            "de_study": "",
            "differential_expression_score": 0.5,
        }
    )


def _score_genes(
    genes: list[str],
    table: dict[str, tuple[float, float]],
    study: str,
    min_abs_log2fc: float,
    max_pvalue: float,
) -> pd.DataFrame:
    rows = []
    for gene in genes:
        held = table.get(gene.upper())
        if held is None:
            rows.append(
                {
                    "candidate_gene_symbol": gene,
                    "log2_fold_change": math.nan,
                    "p_value": math.nan,
                    "de_status": "not_measured",
                    "de_study": study,
                    "differential_expression_score": 0.5,
                }
            )
            continue
        fold, p_value = held
        score = score_change(fold, p_value, min_abs_log2fc=min_abs_log2fc, max_pvalue=max_pvalue)
        rows.append(
            {
                "candidate_gene_symbol": gene,
                "log2_fold_change": fold,
                "p_value": p_value,
                "de_status": "changed" if score > 0 else "unchanged",
                "de_study": study,
                "differential_expression_score": score,
            }
        )
    out = pd.DataFrame(rows)
    out["_abs_fold"] = out["log2_fold_change"].abs().fillna(-1)
    out = out.sort_values(
        ["differential_expression_score", "_abs_fold"],
        ascending=[False, False],
    ).drop(columns="_abs_fold")
    return out.reset_index(drop=True)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Track B Step B4 — differential expression")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    run_step_b4(args.run_id)


if __name__ == "__main__":
    main()
