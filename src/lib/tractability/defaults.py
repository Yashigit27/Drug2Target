"""Conservative constant scores used when OT/PDBe data is unavailable."""

from __future__ import annotations

import pandas as pd

DEFAULT_STRUCTURE = 0.4
DEFAULT_DRUGGABILITY = 0.4
DEFAULT_SAFETY = 0.5


def default_readiness_score() -> float:
    return (
        0.4 * DEFAULT_STRUCTURE
        + 0.4 * DEFAULT_DRUGGABILITY
        + 0.2 * DEFAULT_SAFETY
    )


def score_defaults(symbols: list[str]) -> pd.DataFrame:
    rows = []
    for sym in symbols:
        rows.append(
            {
                "candidate_gene_symbol": sym,
                "structure_availability_score": DEFAULT_STRUCTURE,
                "druggability_score": DEFAULT_DRUGGABILITY,
                "safety_score": DEFAULT_SAFETY,
                "b9_readiness_score": default_readiness_score(),
                "b9_method": "defaults",
            }
        )
    return pd.DataFrame.from_records(rows)
