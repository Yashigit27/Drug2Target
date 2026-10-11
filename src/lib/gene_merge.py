"""
Merge Open Targets rows with literature RAG rows; dedupe by Ensembl id or gene symbol.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


BASE_COLS = [
    "source",
    "disease_ot_id",
    "disease_name",
    "ensembl_gene_id",
    "gene_symbol",
    "association_score",
    "literature_max_rag_score",
    "literature_pmids",
    "literature_snippet",
]


def _merge_pmids(a: str, b: str) -> str:
    parts = {p for p in f"{a};{b}".split(";") if p.strip()}
    return ";".join(sorted(parts))


def merge_opentargets_and_literature(
    df_ot: pd.DataFrame,
    lit_rows: list[dict],
    *,
    disease_ot_id: str | None,
    disease_name: str | None,
) -> pd.DataFrame:
    rows: list[pd.Series] = []

    if not df_ot.empty:
        for _, r in df_ot.iterrows():
            d = r.to_dict()
            d["source"] = "open_targets"
            d["literature_max_rag_score"] = np.nan
            d["literature_pmids"] = ""
            d["literature_snippet"] = ""
            rows.append(pd.Series(d))

    def find_row_idx(ens: str | None, sym: str | None) -> int | None:
        sym_u = (sym or "").strip().upper()
        for i, s in enumerate(rows):
            e = s.get("ensembl_gene_id")
            if isinstance(e, str) and ens and e == ens:
                return i
        for i, s in enumerate(rows):
            g = (s.get("gene_symbol") or "").strip().upper()
            if sym_u and g == sym_u:
                return i
        return None

    for lit in lit_rows:
        ens = lit.get("ensembl_gene_id")
        sym = lit.get("gene_symbol")
        idx = find_row_idx(ens if isinstance(ens, str) else None, sym if isinstance(sym, str) else None)
        lr = lit.get("literature_max_rag_score")
        pm = lit.get("literature_pmids") or ""
        sn = lit.get("literature_snippet") or ""
        if idx is not None:
            s = rows[idx]
            prev = (
                float(s.get("literature_max_rag_score") or 0.0)
                if pd.notna(s.get("literature_max_rag_score"))
                else 0.0
            )
            s["source"] = "open_targets+literature_rag"
            if lr is not None:
                s["literature_max_rag_score"] = max(prev, float(lr))
            s["literature_pmids"] = _merge_pmids(str(s.get("literature_pmids") or ""), pm)
            if not str(s.get("literature_snippet") or "").strip() and sn:
                s["literature_snippet"] = sn
            rows[idx] = s
        else:
            rows.append(
                pd.Series(
                    {
                        "source": "literature_rag",
                        "disease_ot_id": disease_ot_id,
                        "disease_name": disease_name,
                        "ensembl_gene_id": ens,
                        "gene_symbol": sym,
                        "association_score": np.nan,
                        "literature_max_rag_score": lr,
                        "literature_pmids": pm,
                        "literature_snippet": sn,
                    }
                )
            )

    if not rows:
        return pd.DataFrame(columns=BASE_COLS)

    out = pd.DataFrame(rows)
    for c in BASE_COLS:
        if c not in out.columns:
            out[c] = np.nan if c in ("association_score", "literature_max_rag_score") else ""

    out = out.sort_values(
        by=["association_score", "literature_max_rag_score"],
        ascending=[False, False],
        na_position="last",
    )

    ens_ok = out["ensembl_gene_id"].notna() & (out["ensembl_gene_id"].astype(str).str.len() > 0)
    out["_dedup"] = np.where(
        ens_ok,
        out["ensembl_gene_id"].astype(str),
        "sym:" + out["gene_symbol"].astype(str).str.strip().str.upper(),
    )
    out = out.drop_duplicates(subset=["_dedup"], keep="first")
    out = out.drop(columns=["_dedup"], errors="ignore")
    return out[[c for c in BASE_COLS if c in out.columns]]
