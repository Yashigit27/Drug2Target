"""
Fusion / F1 — unified target portfolio across Track A and Track B.

Produces tiered, deduplicated targets for downstream CADD prioritization.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.lib.fusion.paths import step_f1_portfolio_path, step_f1_summary_path
from src.lib.paths import run_dir
from src.lib.settings import load_config
from src.lib.track_a.paths import step_a5_path
from src.lib.track_b.paths import step_b10_path


def _norm_series(s: pd.Series) -> pd.Series:
    vals = pd.to_numeric(s, errors="coerce").fillna(0.0)
    lo, hi = float(vals.min()), float(vals.max())
    if hi <= lo:
        return pd.Series([0.0] * len(vals), index=vals.index)
    return (vals - lo) / (hi - lo)


def _tier(row: pd.Series, cfg) -> str:
    a = float(row.get("track_a_score_norm") or 0.0)
    b = float(row.get("track_b_score_norm") or 0.0)
    tissue = float(row.get("tissue_relevance_score") or 0.5)
    cadd = float(row.get("cadd_readiness_score") or 0.0)
    if a >= cfg.tier1_track_threshold and b >= cfg.tier1_track_threshold:
        return "Tier 1"
    if (a >= cfg.tier1_track_threshold or b >= cfg.tier1_track_threshold) and tissue >= cfg.tier1_tissue_threshold:
        return "Tier 1"
    if cadd >= cfg.tier1_cadd_threshold and (a >= cfg.tier2_track_threshold or b >= cfg.tier2_track_threshold):
        return "Tier 1"
    if a >= cfg.tier2_track_threshold or b >= cfg.tier2_track_threshold:
        return "Tier 2"
    return "Tier 3"


def run_step_f1(run_id: str) -> Path:
    cfg = load_config().fusion
    base = run_dir(run_id)
    ta_path = step_a5_path(run_id)
    tb_path = step_b10_path(run_id)

    ta = pd.read_csv(ta_path) if ta_path.is_file() else pd.DataFrame()
    tb = pd.read_csv(tb_path) if tb_path.is_file() else pd.DataFrame()
    if ta.empty and tb.empty:
        raise FileNotFoundError("Run Track A and/or Track B before F1 fusion.")

    rows: list[dict] = []

    if not ta.empty:
        for _, r in ta.iterrows():
            rows.append(
                {
                    "gene_symbol": str(r.get("gene_symbol") or "").upper(),
                    "ensembl_gene_id": r.get("ensembl_gene_id"),
                    "track_a_rank": r.get("rank"),
                    "track_a_score": r.get("final_known_track_a_score"),
                    "track_b_rank": None,
                    "track_b_score": None,
                    "cadd_readiness_score": r.get("cadd_readiness_score"),
                    "tissue_relevance_score": r.get("tissue_relevance_score"),
                    "source_tracks": "track_a",
                }
            )

    if not tb.empty:
        tb_tissue = {
            str(r.get("candidate_gene_symbol") or "").upper(): r.get("tissue_relevance_score")
            for _, r in tb.iterrows()
        }
        for _, r in tb.iterrows():
            sym = str(r.get("candidate_gene_symbol") or "").upper()
            existing = next((x for x in rows if x["gene_symbol"] == sym), None)
            if existing:
                existing["track_b_rank"] = r.get("rank")
                existing["track_b_score"] = r.get("final_novel_score")
                if existing.get("tissue_relevance_score") is None:
                    existing["tissue_relevance_score"] = tb_tissue.get(sym)
                existing["source_tracks"] = "both" if existing["source_tracks"] == "track_a" else "track_b"
            else:
                rows.append(
                    {
                        "gene_symbol": sym,
                        "ensembl_gene_id": None,
                        "track_a_rank": None,
                        "track_a_score": None,
                        "track_b_rank": r.get("rank"),
                        "track_b_score": r.get("final_novel_score"),
                        "cadd_readiness_score": None,
                        "tissue_relevance_score": tb_tissue.get(sym),
                        "source_tracks": "track_b",
                    }
                )

    df = pd.DataFrame.from_records(rows)
    df["track_a_score_norm"] = _norm_series(df["track_a_score"].fillna(0.0))
    df["track_b_score_norm"] = _norm_series(df["track_b_score"].fillna(0.0))
    df["tissue_relevance_score"] = pd.to_numeric(df["tissue_relevance_score"], errors="coerce").fillna(0.5)
    df["cadd_readiness_score"] = pd.to_numeric(df["cadd_readiness_score"], errors="coerce").fillna(0.0)

    w = cfg.portfolio_weights
    df["portfolio_score"] = (
        w.get("track_a", 0.35) * df["track_a_score_norm"]
        + w.get("track_b", 0.35) * df["track_b_score_norm"]
        + w.get("tissue", 0.15) * df["tissue_relevance_score"]
        + w.get("cadd", 0.15) * _norm_series(df["cadd_readiness_score"])
    )
    df["tier"] = df.apply(lambda r: _tier(r, cfg), axis=1)
    df = df.sort_values(["tier", "portfolio_score"], ascending=[True, False]).reset_index(drop=True)
    df["portfolio_rank"] = df.index + 1

    out_cols = [
        "portfolio_rank",
        "tier",
        "gene_symbol",
        "ensembl_gene_id",
        "portfolio_score",
        "source_tracks",
        "track_a_rank",
        "track_a_score",
        "track_b_rank",
        "track_b_score",
        "tissue_relevance_score",
        "cadd_readiness_score",
    ]
    out = df[out_cols]
    out_path = step_f1_portfolio_path(run_id)
    out.to_csv(out_path, index=False)

    summary = {
        "run_id": run_id,
        "total_targets": len(out),
        "tier_counts": out["tier"].value_counts().to_dict(),
        "both_tracks": int((out["source_tracks"] == "both").sum()),
        "track_a_only": int((out["source_tracks"] == "track_a").sum()),
        "track_b_only": int((out["source_tracks"] == "track_b").sum()),
    }
    step_f1_summary_path(run_id).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Fusion F1 — unified target portfolio")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_f1(args.run_id)


if __name__ == "__main__":
    main()
