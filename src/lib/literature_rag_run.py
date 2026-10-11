"""
Orchestrate Europe PMC → chunk → TF‑IDF retrieval → gene extraction → mygene validation.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import httpx

from src.lib.http_client import make_http_client

from src.lib.europepmc_client import build_disease_literature_query, search_articles
from src.lib.literature_genes import (
    aggregate_literature_evidence,
    extract_gene_like_symbols,
    validate_symbols_human,
)
from src.lib.models import Manifest
from src.lib.rag_retrieval import chunk_abstract, tfidf_top_chunks
from src.lib.settings import LiteratureRagConfig, load_config


def run_literature_rag(
    manifest: Manifest,
    *,
    client: httpx.Client | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (literature_gene_rows, cache_payload_for_json).

    literature_gene_rows match merge_opentargets_and_literature expectations.
    """
    cfg = load_config().literature_rag
    own = client is None
    if own:
        client = make_http_client()
    assert client is not None

    try:
        return _run_literature_rag_body(manifest, client, cfg)
    finally:
        if own:
            client.close()


def _run_literature_rag_body(
    manifest: Manifest,
    client: httpx.Client,
    cfg: LiteratureRagConfig,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    # Prefer the user's primary disease phrase for recall; ontology names can be too narrow for abstracts.
    primary = manifest.input.disease_label.strip()
    fallback_name = (manifest.disease_resolution.selected.name or primary).strip()
    query = build_disease_literature_query(
        primary,
        years_back=cfg.first_pdate_years_back,
    )

    articles = search_articles(
        query,
        client=client,
        page_size=cfg.page_size,
        max_records=cfg.max_articles,
    )
    if not articles and fallback_name.lower() != primary.lower():
        query = build_disease_literature_query(
            fallback_name,
            years_back=cfg.first_pdate_years_back,
        )
        articles = search_articles(
            query,
            client=client,
            page_size=cfg.page_size,
            max_records=cfg.max_articles,
        )

    chunks: list[dict] = []
    for a in articles:
        pmid = str(a.get("pmid") or a.get("id") or "")
        chs = chunk_abstract(
            pmid,
            a.get("title") or "",
            a.get("abstractText") or "",
            max_chunks=cfg.chunks_per_abstract_max,
            chunk_max_chars=cfg.chunk_max_chars,
        )
        chunks.extend(chs)

    retrieval_q = cfg.retrieval_query
    scored = tfidf_top_chunks(retrieval_q, chunks, top_k=cfg.top_chunks_global)

    freq: Counter[str] = Counter()
    for _, ch in scored:
        for s in extract_gene_like_symbols(ch["text"]):
            freq[s] += 1
    symbols = {s for s, _ in freq.most_common(cfg.max_genes_per_run)}

    validated = validate_symbols_human(symbols)
    sym_meta = {k.upper(): v for k, v in validated.items()}

    lit_rows = aggregate_literature_evidence(scored, sym_meta)

    cache = {
        "europepmc_query": query,
        "article_count": len(articles),
        "chunk_count": len(chunks),
        "scored_chunk_count": len(scored),
        "symbols_extracted": len(symbols),
        "symbols_validated_human": len(sym_meta),
        "literature_row_count": len(lit_rows),
    }

    return lit_rows, cache
