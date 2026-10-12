"""STRING neighborhood proxy used when GTEx data is unavailable."""

from __future__ import annotations

import pandas as pd

from src.lib.track_b.scoring import minmax


def score_string_proxy(b1: pd.DataFrame) -> pd.DataFrame:
    """Return candidate scores from B1 seed_count + mean_string_score."""
    seed_norm = minmax(b1["seed_count"].fillna(0.0).astype(float).tolist())
    score_norm = minmax(b1["mean_string_score"].fillna(0.0).astype(float).tolist())
    out = b1[["candidate_gene_symbol"]].copy()
    out["string_proxy_score"] = [
        0.6 * s + 0.4 * m for s, m in zip(seed_norm, score_norm, strict=False)
    ]
    out["b3_method"] = "string_proxy"
    return out
