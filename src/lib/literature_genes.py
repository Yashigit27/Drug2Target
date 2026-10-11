"""
Extract human gene symbols from text and validate with mygene.

Heuristic: ALLCAPS tokens → mygene human symbol lookup (authoritative filter).
"""

from __future__ import annotations

import re
import mygene

# Common English / methods acronyms that are not gene symbols (incomplete list)
_STOP = frozenset(
    {
        "THE",
        "AND",
        "OR",
        "RNA",
        "DNA",
        "PCR",
        "MRI",
        "PET",
        "EEG",
        "USA",
        "UK",
        "WHO",
        "NIH",
        "FDA",
        "CSF",
        "CNS",
        "ROS",
        "ATP",
        "GTP",
        "NMDA",
        "BBB",
        "AD",
        "PD",
        "MS",
        "GWAS",
        "SNP",
        "SNPS",
        "IV",
        "IM",
        "IP",
        "ELISA",
        "WT",
        "KO",
        "KD",
        "OE",
    }
)


_GENE_LIKE = re.compile(r"\b([A-Z][A-Z0-9]{1,9})\b")


def extract_gene_like_symbols(text: str) -> set[str]:
    found = set()
    for m in _GENE_LIKE.finditer(text):
        s = m.group(1)
        if s in _STOP:
            continue
        if len(s) < 2:
            continue
        found.add(s)
    return found


def validate_symbols_human(
    symbols: set[str],
    *,
    max_query: int = 200,
) -> dict[str, dict]:
    """
    Map symbol → mygene record (human). Returns dict symbol -> {ensembl, symbol, ...}
    Batches to avoid huge requests.
    """
    out: dict[str, dict] = {}
    syms = sorted(symbols)
    if not syms:
        return out
    mg = mygene.MyGeneInfo()
    for i in range(0, len(syms), max_query):
        batch = syms[i : i + max_query]
        res = mg.querymany(
            batch,
            scopes="symbol",
            fields="symbol,ensembl.gene,genomic_pos",
            species="human",
            as_dataframe=False,
            verbose=False,
        )
        for row in res:
            if row.get("notfound"):
                continue
            sym = row.get("query") or row.get("symbol")
            if not sym:
                continue
            eg = row.get("ensembl")
            ensembl_id = None
            if isinstance(eg, dict):
                ensembl_id = eg.get("gene")
            elif isinstance(eg, list) and eg:
                ensembl_id = eg[0].get("gene") if isinstance(eg[0], dict) else None
            out[str(sym).upper()] = {
                "symbol": row.get("symbol") or sym,
                "ensembl_gene_id": ensembl_id,
                "mygene_id": row.get("_id"),
            }
    return out


def aggregate_literature_evidence(
    scored_chunks: list[tuple[float, dict]],
    symbol_to_meta: dict[str, dict],
) -> list[dict]:
    """
    For each validated symbol, aggregate max RAG score + PMIDs + one snippet.
    """
    by_sym: dict[str, dict] = {}
    for score, ch in scored_chunks:
        text = ch["text"]
        pmid = ch["pmid"]
        for sym in extract_gene_like_symbols(text):
            key = sym.upper()
            if key not in symbol_to_meta:
                continue
            meta = symbol_to_meta[key]
            row = by_sym.get(key)
            if row is None:
                by_sym[key] = {
                    "gene_symbol": meta.get("symbol", key),
                    "ensembl_gene_id": meta.get("ensembl_gene_id"),
                    "literature_max_rag_score": score,
                    "literature_pmids": {pmid},
                    "literature_snippet": text[:400],
                }
            else:
                row["literature_max_rag_score"] = max(row["literature_max_rag_score"], score)
                row["literature_pmids"].add(pmid)
                if len(row["literature_snippet"]) < 50:
                    row["literature_snippet"] = text[:400]
    rows = []
    for _key, row in by_sym.items():
        pmids = sorted(row["literature_pmids"], key=lambda x: (len(x), x))
        rows.append(
            {
                "gene_symbol": row["gene_symbol"],
                "ensembl_gene_id": row["ensembl_gene_id"],
                "literature_max_rag_score": row["literature_max_rag_score"],
                "literature_pmids": ";".join(pmids),
                "literature_snippet": row["literature_snippet"],
            }
        )
    rows.sort(key=lambda r: (-(r["literature_max_rag_score"] or 0), r["gene_symbol"]))
    return rows
