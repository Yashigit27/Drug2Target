"""Generate human-readable analysis report from run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.lib.fusion.paths import step_f1_portfolio_path, step_f1_summary_path
from src.lib.paths import run_dir
from web.runs import run_status


def _top_rows(path: Path, n: int = 5) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    df = pd.read_csv(path).head(n)
    return df.fillna("").astype(str).to_dict(orient="records")


def _explain_track_a(row: dict[str, str]) -> str:
    gene = row.get("gene_symbol", "?")
    score = row.get("final_known_track_a_score", "")
    action = row.get("crowded_action", "keep")
    cadd = row.get("cadd_readiness_score", "")
    tissue = row.get("tissue_relevance_score", "")
    reason = row.get("selection_reason", "")
    return (
        f"{gene} is a known disease-linked target ranked for Track A (score {score}). "
        f"Crowdedness action: {action}. CADD readiness proxy: {cadd}. "
        f"Tissue relevance: {tissue}. Component scores: {reason}."
    )


def _explain_track_b(row: dict[str, str]) -> str:
    gene = row.get("candidate_gene_symbol", "?")
    score = row.get("final_novel_score", "")
    tissue = row.get("tissue_relevance_score", "")
    reason = row.get("selection_reason", "")
    return (
        f"{gene} is a novel network-expanded candidate (score {score}). "
        f"Tissue relevance: {tissue}. Ranked via STRING neighborhood, pathway overlap, "
        f"expression proxies, and novelty. Details: {reason}."
    )


def _explain_fusion(row: dict[str, str]) -> str:
    return (
        f"{row.get('gene_symbol', '?')} — tier {row.get('tier', '?')}, portfolio score "
        f"{row.get('portfolio_score', '?')}. Sources: {row.get('source_tracks', '?')}. "
        f"Track A score: {row.get('track_a_score', '-')}; Track B score: {row.get('track_b_score', '-')}; "
        f"tissue: {row.get('tissue_relevance_score', '-')}; CADD readiness: {row.get('cadd_readiness_score', '-')}."
    )


def build_report(run_id: str, *, include_llm: bool = True) -> dict[str, Any]:
    status = run_status(run_id)
    if not status.get("exists"):
        raise FileNotFoundError(f"Run not found: {run_id}")

    base = run_dir(run_id)
    manifest = status.get("manifest") or {}
    disease = manifest.get("disease_resolution", {}).get("selected", {})
    tissue = (manifest.get("input") or {}).get("tissue")

    known_path = base / "artifacts" / "known_disease_genes.csv"
    ta_path = base / "artifacts" / "track_a" / "ranked_known_targets.csv"
    tb_path = base / "artifacts" / "track_b" / "ranked_novel_candidates.csv"
    f1_path = step_f1_portfolio_path(run_id)

    known_count = len(pd.read_csv(known_path)) if known_path.is_file() else 0
    track_a = _top_rows(ta_path, 5)
    track_b = _top_rows(tb_path, 5)
    fusion = _top_rows(f1_path, 5)

    sections: list[dict[str, Any]] = [
        {
            "title": "Run summary",
            "body": (
                f"Disease: {disease.get('name', '?')} ({disease.get('id', '?')}). "
                f"Tissue context: {tissue or 'not specified'}. "
                f"Collected {known_count} known/merged disease genes from Open Targets "
                f"and optional literature RAG."
            ),
        },
    ]

    if fusion:
        summary = {}
        sp = step_f1_summary_path(run_id)
        if sp.is_file():
            summary = json.loads(sp.read_text(encoding="utf-8"))
        sections.append(
            {
                "title": "Fusion F1 - Unified target portfolio",
                "subtitle": "Tiered merge of Track A and Track B for CADD prioritization",
                "body": f"Tier counts: {summary.get('tier_counts', {})}",
                "targets": [
                    {
                        "rank": i + 1,
                        "gene": r.get("gene_symbol", "?"),
                        "score": r.get("portfolio_score", ""),
                        "tier": r.get("tier", ""),
                        "explain": _explain_fusion(r),
                    }
                    for i, r in enumerate(fusion)
                ],
            }
        )

    if track_a:
        sections.append(
            {
                "title": "Track A - Top underexplored known targets",
                "subtitle": "Known disease-linked genes ranked for low crowdedness and CADD readiness",
                "targets": [
                    {
                        "rank": i + 1,
                        "gene": r.get("gene_symbol", "?"),
                        "score": r.get("final_known_track_a_score", ""),
                        "explain": _explain_track_a(r),
                    }
                    for i, r in enumerate(track_a)
                ],
            }
        )

    if track_b:
        sections.append(
            {
                "title": "Track B - Top novel candidates",
                "subtitle": "STRING-expanded neighbors scored across network, pathway, and novelty",
                "targets": [
                    {
                        "rank": i + 1,
                        "gene": r.get("candidate_gene_symbol", "?"),
                        "score": r.get("final_novel_score", ""),
                        "explain": _explain_track_b(r),
                    }
                    for i, r in enumerate(track_b)
                ],
            }
        )

    sections.append(
        {
            "title": "Method notes",
            "body": (
                "Track A prioritizes known associations with lower literature crowding. "
                "Track B expands STRING PPI neighborhoods and ranks novel candidates. "
                "Fusion F1 deduplicates and tiers targets across both tracks. "
                "Tissue filtering combines literature snippets, Europe PMC tissue co-mentions, "
                "and mygene summaries when a tissue is specified."
            ),
        }
    )

    result: dict[str, Any] = {
        "run_id": run_id,
        "disease": disease.get("name"),
        "ontology_id": disease.get("id"),
        "tissue": tissue,
        "known_gene_count": known_count,
        "steps_completed": sum(1 for s in status.get("steps", []) if s.get("done")),
        "has_track_a": bool(track_a),
        "has_track_b": bool(track_b),
        "has_fusion": bool(fusion),
        "sections": sections,
    }

    if include_llm and fusion:
        try:
            from web.llm_narrative import generate_run_narrative

            result["llm_narrative"] = generate_run_narrative(run_id, top_n=3)
        except Exception as exc:
            result["llm_narrative"] = {"error": str(exc), "sections": []}

    return result
