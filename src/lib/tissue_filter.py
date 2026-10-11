"""
Tissue-context scoring for targets and candidates.

Combines literature snippet mentions, Europe PMC tissue co-mentions,
and optional mygene summary text when a tissue keyword is provided.
"""

from __future__ import annotations

import re
from functools import lru_cache

import httpx

from src.lib.http_client import make_http_client

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

_TISSUE_ALIASES: dict[str, list[str]] = {
    "brain": ["brain", "cortex", "neuron", "neuronal", "cns", "hippocampus", "striatum"],
    "liver": ["liver", "hepatocyte", "hepatic"],
    "heart": ["heart", "cardiac", "myocard", "cardiomyocyte"],
    "lung": ["lung", "pulmonary", "alveolar"],
    "kidney": ["kidney", "renal", "nephron"],
    "blood": ["blood", "hematopoietic", "leukocyte", "pbmc"],
    "skin": ["skin", "epiderm", "keratinocyte"],
    "muscle": ["muscle", "skeletal muscle", "myocyte"],
    "pancreas": ["pancreas", "pancreatic", "islet"],
    "colon": ["colon", "intestinal", "gut", "enterocyte"],
}


def tissue_keywords(tissue: str | None) -> list[str]:
    if not tissue:
        return []
    key = tissue.strip().lower()
    if not key:
        return []
    aliases = _TISSUE_ALIASES.get(key, [])
    terms = [key] + [a for a in aliases if a != key]
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def snippet_tissue_score(text: str, tissue: str | None) -> float:
    terms = tissue_keywords(tissue)
    if not terms:
        return 0.5
    t = (text or "").lower()
    if not t:
        return 0.35
    hits = sum(1 for kw in terms if kw in t)
    if hits >= 2:
        return 1.0
    if hits == 1:
        return 0.85
    return 0.3


def _epmc_hit_count(client: httpx.Client, query: str) -> int:
    try:
        r = client.get(EPMC, params={"query": query, "format": "json", "pageSize": 1}, timeout=45.0)
        r.raise_for_status()
        return int((r.json() or {}).get("hitCount") or 0)
    except Exception:
        return 0


def literature_tissue_score(
    client: httpx.Client,
    *,
    disease: str,
    gene: str,
    tissue: str | None,
) -> float:
    terms = tissue_keywords(tissue)
    if not terms or not disease or not gene:
        return 0.5
    tissue_clause = " OR ".join(f'"{kw}"' for kw in terms[:4])
    q = f'ABSTRACT:"{disease}" AND {gene} AND ({tissue_clause})'
    hits = _epmc_hit_count(client, q)
    if hits >= 10:
        return 1.0
    if hits >= 3:
        return 0.8
    if hits >= 1:
        return 0.65
    return 0.35


@lru_cache(maxsize=256)
def _mygene_summary(symbol: str) -> str:
    try:
        import mygene

        mg = mygene.MyGeneInfo()
        res = mg.query(symbol, species="human", fields="summary,symbol", size=1)
        hits = (res or {}).get("hits") or []
        if not hits:
            return ""
        return str(hits[0].get("summary") or "")
    except Exception:
        return ""


def mygene_tissue_score(gene_symbol: str, tissue: str | None) -> float:
    summary = _mygene_summary(gene_symbol.strip().upper())
    return snippet_tissue_score(summary, tissue)


def combined_tissue_score(
    *,
    snippet: str,
    gene_symbol: str,
    disease: str,
    tissue: str | None,
    client: httpx.Client | None = None,
    weights: dict[str, float] | None = None,
) -> dict[str, float]:
    w = weights or {"snippet": 0.35, "literature": 0.40, "mygene": 0.25}
    snippet_s = snippet_tissue_score(snippet, tissue)
    mygene_s = mygene_tissue_score(gene_symbol, tissue)
    if client is not None and tissue:
        lit_s = literature_tissue_score(client, disease=disease, gene=gene_symbol, tissue=tissue)
    else:
        lit_s = 0.5
    total_w = sum(w.values()) or 1.0
    score = (w["snippet"] * snippet_s + w["literature"] * lit_s + w["mygene"] * mygene_s) / total_w
    return {
        "tissue_relevance_score": round(score, 4),
        "tissue_snippet_score": round(snippet_s, 4),
        "tissue_literature_score": round(lit_s, 4),
        "tissue_mygene_score": round(mygene_s, 4),
    }


def normalize_tissue_label(tissue: str | None) -> str | None:
    if not tissue:
        return None
    cleaned = re.sub(r"\s+", " ", tissue.strip().lower())
    return cleaned or None
