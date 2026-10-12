from __future__ import annotations

import time
from typing import Any

import httpx
import mygene

from src.lib.track_a.sources import europepmc_hit_count, fetch_target_profile


STRING_PARTNERS = "https://string-db.org/api/json/interaction_partners"


def string_interaction_partners(
    client: httpx.Client,
    *,
    gene_symbol: str,
    required_score: int = 400,
    limit: int = 40,
) -> list[dict[str, Any]]:
    r = client.get(
        STRING_PARTNERS,
        params={
            "identifiers": gene_symbol,
            "species": 9606,
            "required_score": required_score,
            "limit": limit,
        },
        timeout=120.0,
    )
    r.raise_for_status()
    return r.json() or []


def _querymany_with_retry(mg: mygene.MyGeneInfo, batch: list[str], **kwargs: Any) -> list:
    """Retry mygene calls on transient 5xx / network errors."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            return mg.querymany(batch, **kwargs)
        except Exception as exc:
            last_exc = exc
            msg = str(exc).lower()
            transient = any(
                tok in msg
                for tok in ("502", "503", "504", "timeout", "temporarily", "connection")
            )
            if not transient or attempt == 2:
                raise
            wait = 2.0 * (attempt + 1)
            print(f"mygene retry {attempt + 1}/3 after error: {exc} (sleep {wait:.0f}s)")
            time.sleep(wait)
    raise last_exc  # pragma: no cover


def mygene_annotations(symbols: list[str]) -> dict[str, dict[str, Any]]:
    mg = mygene.MyGeneInfo()
    out: dict[str, dict[str, Any]] = {}
    if not symbols:
        return out
    for i in range(0, len(symbols), 200):
        batch = symbols[i : i + 200]
        res = _querymany_with_retry(
            mg,
            batch,
            scopes="symbol",
            fields="symbol,ensembl.gene,go.BP.id,pathway.reactome.id,interpro.id",
            species="human",
            as_dataframe=False,
            verbose=False,
        )
        for row in res:
            if row.get("notfound"):
                continue
            q = str((row.get("query") or row.get("symbol") or "")).upper().strip()
            if not q:
                continue
            out[q] = row
    return out


def extract_id_set(payload: object, key: str) -> set[str]:
    """
    Extract ids from mygene nested fields for keys like:
    - go.BP.id
    - pathway.reactome.id
    - interpro.id
    """
    if payload is None:
        return set()
    if isinstance(payload, dict):
        if key in payload and isinstance(payload[key], str):
            return {payload[key]}
        vals = set()
        for v in payload.values():
            vals |= extract_id_set(v, key)
        return vals
    if isinstance(payload, list):
        vals = set()
        for v in payload:
            vals |= extract_id_set(v, key)
        return vals
    return set()
