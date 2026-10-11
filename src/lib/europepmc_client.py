"""
Europe PMC REST search — abstracts for literature-grounded RAG retrieval.

Docs: https://europepmc.org/RestfulWebService
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _sanitize_term(s: str) -> str:
    s = s.strip()
    s = re.sub(r'[\[\](){}":]', " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_disease_literature_query(
    disease_label: str,
    *,
    years_back: int,
) -> str:
    """
    Build a Europe PMC query: recent PDATE + disease in abstract + target-like terms.

    Using ABSTRACT: avoids matching incidental TITLE-only hits; FIRST_PDATE biases to recent work.
    """
    label = _sanitize_term(disease_label)
    if not label:
        raise ValueError("disease_label is empty")
    now = datetime.now(timezone.utc).year
    start_y = max(1970, now - int(years_back))
    # Inclusive range through end of current year
    pto = f"{now}-12-31"
    pfrom = f"{start_y}-01-01"
    # Target / mechanism language helps TF‑IDF + downstream extraction
    return (
        f'ABSTRACT:"{label}" AND (gene OR target OR therapeutic OR protein OR pathway) '
        f"AND FIRST_PDATE:[{pfrom} TO {pto}]"
    )


def search_articles(
    query: str,
    *,
    client: httpx.Client,
    page_size: int = 20,
    max_records: int = 40,
) -> list[dict[str, Any]]:
    """
    Paginate Europe PMC `search` until max_records or no next cursor.
    Each item: pmid, title, abstractText, pubYear, id, source.
    """
    out: list[dict[str, Any]] = []
    cursor: str | None = "*"
    while len(out) < max_records and cursor:
        params: dict[str, Any] = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": min(page_size, max_records - len(out)),
            "cursorMark": cursor,
        }
        r = client.get(BASE, params=params, timeout=120.0)
        r.raise_for_status()
        payload = r.json()
        rl = payload.get("resultList") or {}
        batch = rl.get("result") or []
        if not batch:
            break
        for row in batch:
            pmid = row.get("pmid")
            ab = (row.get("abstractText") or "").strip()
            title = (row.get("title") or "").strip()
            if not ab and not title:
                continue
            out.append(
                {
                    "pmid": str(pmid) if pmid is not None else row.get("id", ""),
                    "title": title,
                    "abstractText": ab,
                    "pubYear": row.get("pubYear"),
                    "source": row.get("source"),
                    "id": row.get("id"),
                }
            )
            if len(out) >= max_records:
                break
        cursor = payload.get("nextCursorMark")
        if cursor == "*":
            cursor = None
        if len(batch) < params["pageSize"]:
            break
    return out[:max_records]
