"""Orchestrate B3 coexpression scoring (STRING / GTEx / hybrid)."""

from __future__ import annotations

import pandas as pd

from src.lib.expression.gtex_lookup import score_gtex_tissue
from src.lib.expression.string_proxy import score_string_proxy
from src.lib.settings import B3CoexpressionConfig, load_config


def score_b3_coexpression(
    b1: pd.DataFrame,
    *,
    tissue: str | None = None,
    cfg: B3CoexpressionConfig | None = None,
) -> pd.DataFrame:
    """
    Produce B3 scores for Track B candidates.

    Always includes:
      - candidate_gene_symbol
      - coexpression_proxy_score   (consumed by B10)
      - b3_method
    """
    if b1.empty:
        raise ValueError("B1 output empty")
    if "candidate_gene_symbol" not in b1.columns:
        raise ValueError("B1 missing candidate_gene_symbol")

    cfg = cfg or load_config().track_b.b3
    provider = (cfg.provider or "hybrid").strip().lower()
    string_df = score_string_proxy(b1)

    if provider == "string_proxy":
        return _finalize_string_only(string_df)

    gtex_df = score_gtex_tissue(b1, tissue=tissue, cfg=cfg)

    if gtex_df is None:
        if provider == "gtex_tissue":
            print("B3: GTEx unavailable; safely falling back to string_proxy")
        return _finalize_string_only(string_df)

    return _finalize_with_gtex(string_df, gtex_df, cfg=cfg, provider=provider)


def _finalize_string_only(string_df: pd.DataFrame) -> pd.DataFrame:
    out = string_df.copy()
    out["coexpression_proxy_score"] = out["string_proxy_score"]
    out["b3_method"] = "string_proxy"
    cols = [
        "candidate_gene_symbol",
        "coexpression_proxy_score",
        "string_proxy_score",
        "b3_method",
    ]
    out = out[cols].sort_values("coexpression_proxy_score", ascending=False)
    return out.reset_index(drop=True)


def _finalize_with_gtex(
    string_df: pd.DataFrame,
    gtex_df: pd.DataFrame,
    *,
    cfg: B3CoexpressionConfig,
    provider: str,
) -> pd.DataFrame:
    merged = string_df.merge(gtex_df, on="candidate_gene_symbol", how="left")
    w_expr = max(0.0, float(cfg.expression_weight))
    w_str = max(0.0, float(cfg.string_proxy_weight))
    total = w_expr + w_str
    if total <= 0:
        w_expr, w_str, total = 0.7, 0.3, 1.0

    scores: list[float] = []
    methods: list[str] = []
    for _, r in merged.iterrows():
        sp = float(r["string_proxy_score"])
        gx = r.get("gtex_expression_score")
        has_gtex = gx is not None and pd.notna(gx)
        if provider == "gtex_tissue":
            if has_gtex:
                scores.append(float(gx))
                methods.append("gtex_tissue")
            else:
                scores.append(sp)
                methods.append("string_proxy_fallback")
        else:  # hybrid
            if has_gtex:
                scores.append((w_expr * float(gx) + w_str * sp) / total)
                methods.append("hybrid")
            else:
                scores.append(sp)
                methods.append("string_proxy_fallback")

    merged["coexpression_proxy_score"] = scores
    merged["b3_method"] = methods
    cols = [
        "candidate_gene_symbol",
        "coexpression_proxy_score",
        "string_proxy_score",
        "ensembl_gene_id",
        "gtex_tissue",
        "tissue_tpm",
        "gtex_expression_score",
        "b3_method",
    ]
    # ensembl etc. may be missing if merge odd — keep available
    cols = [c for c in cols if c in merged.columns]
    out = merged[cols].sort_values("coexpression_proxy_score", ascending=False)
    return out.reset_index(drop=True)
