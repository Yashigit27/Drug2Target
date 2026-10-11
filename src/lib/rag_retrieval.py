"""
Lightweight RAG *retrieval*: TF‑IDF ranking of abstract chunks (no LLM).

Suitable for CPU-only pipelines; swap to embeddings later without changing Step 2 contract.
"""

from __future__ import annotations

import re
from typing import TypedDict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TextChunk(TypedDict):
    pmid: str
    text: str


def chunk_abstract(
    pmid: str,
    title: str,
    abstract: str,
    *,
    max_chunks: int,
    chunk_max_chars: int,
) -> list[TextChunk]:
    """Split title + abstract into sentence-ish chunks for retrieval."""
    blob = f"{title}. {abstract}".strip()
    if not blob:
        return []
    # Split on sentence boundaries; fall back to length windows
    parts = re.split(r"(?<=[.!?])\s+", blob)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(buf) + len(p) + 1 <= chunk_max_chars:
            buf = f"{buf} {p}".strip() if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
            while len(buf) > chunk_max_chars:
                chunks.append(buf[:chunk_max_chars])
                buf = buf[chunk_max_chars:].lstrip()
    if buf:
        chunks.append(buf)
    # Hard-cap per abstract
    chunks = chunks[:max_chunks]
    return [{"pmid": pmid, "text": c} for c in chunks if c.strip()]


def tfidf_top_chunks(
    query: str,
    chunks: list[TextChunk],
    top_k: int,
) -> list[tuple[float, TextChunk]]:
    if not chunks or top_k <= 0:
        return []
    corpus = [c["text"] for c in chunks]
    vec = TfidfVectorizer(
        lowercase=True,
        ngram_range=(1, 2),
        max_features=50_000,
        token_pattern=r"(?u)\b\w\w+\b",
    )
    try:
        X = vec.fit_transform(corpus + [query])
    except ValueError:
        return []
    qv = X[-1]
    dv = X[:-1]
    sims = cosine_similarity(qv, dv).ravel()
    order = np.argsort(-sims)[:top_k]
    return [(float(sims[i]), chunks[i]) for i in order if sims[i] > 0]
