"""Evidence cards for individual genes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.lib.fusion.paths import step_f1_portfolio_path, step_f1_summary_path
from src.lib.paths import manifest_path, run_dir
from src.lib.run_manifest import read_manifest
from src.lib.track_a.paths import step_a5_path
from src.lib.track_b.paths import step_b10_path, step_b1_path, step_b7_path


def _row_for_gene(df: pd.DataFrame, gene: str, col: str = "gene_symbol") -> dict[str, Any] | None:
    if df.empty:
        return None
    if col not in df.columns:
        if "candidate_gene_symbol" in df.columns:
            col = "candidate_gene_symbol"
        else:
            return None
    hit = df[df[col].astype(str).str.upper() == gene.upper()]
    if hit.empty:
        return None
    return hit.iloc[0].fillna("").astype(str).to_dict()


def build_evidence_card(run_id: str, gene: str) -> dict[str, Any]:
    base = run_dir(run_id)
    if not base.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")

    gene_u = gene.strip().upper()
    manifest = read_manifest(manifest_path(run_id))
    known_path = base / "artifacts" / "known_disease_genes.csv"
    known = pd.read_csv(known_path) if known_path.is_file() else pd.DataFrame()
    known_row = _row_for_gene(known, gene_u, "gene_symbol")

    ta = pd.read_csv(step_a5_path(run_id)) if step_a5_path(run_id).is_file() else pd.DataFrame()
    tb = pd.read_csv(step_b10_path(run_id)) if step_b10_path(run_id).is_file() else pd.DataFrame()
    f1 = pd.read_csv(step_f1_portfolio_path(run_id)) if step_f1_portfolio_path(run_id).is_file() else pd.DataFrame()
    b1 = pd.read_csv(step_b1_path(run_id)) if step_b1_path(run_id).is_file() else pd.DataFrame()
    b7 = pd.read_csv(step_b7_path(run_id)) if step_b7_path(run_id).is_file() else pd.DataFrame()

    card: dict[str, Any] = {
        "run_id": run_id,
        "gene_symbol": gene_u,
        "disease": manifest.input.disease_label,
        "tissue": manifest.input.tissue,
        "subtype": manifest.input.disease_subtype,
        "ontology_id": manifest.disease_resolution.selected.id,
        "ontology_name": manifest.disease_resolution.selected.name,
        "known_association": known_row,
        "track_a": _row_for_gene(ta, gene_u, "gene_symbol"),
        "track_b": _row_for_gene(tb, gene_u, "candidate_gene_symbol"),
        "fusion": _row_for_gene(f1, gene_u, "gene_symbol"),
        "network": {},
        "literature": {},
    }

    if known_row:
        pmids = str(known_row.get("literature_pmids") or "")
        card["literature"] = {
            "pmids": [p.strip() for p in pmids.split(";") if p.strip()],
            "max_rag_score": known_row.get("literature_max_rag_score"),
            "snippet": known_row.get("literature_snippet"),
            "association_score": known_row.get("association_score"),
            "source": known_row.get("source"),
        }

    if not b1.empty and "candidate_gene_symbol" in b1.columns:
        nb = b1[b1["candidate_gene_symbol"].astype(str).str.upper() == gene_u]
        if not nb.empty:
            card["network"] = {
                "seed_count": nb.iloc[0].get("seed_count"),
                "mean_string_score": nb.iloc[0].get("mean_string_score"),
                "max_string_score": nb.iloc[0].get("max_string_score"),
            }
    if not b7.empty:
        n7 = _row_for_gene(b7, gene_u, "candidate_gene_symbol")
        if n7:
            card["network"]["prioritization_score"] = n7.get("network_prioritization_score")

    summary_path = step_f1_summary_path(run_id)
    if summary_path.is_file():
        card["fusion_summary"] = json.loads(summary_path.read_text(encoding="utf-8"))

    return card
