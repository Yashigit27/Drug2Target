from __future__ import annotations

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


def mygene_annotations(symbols: list[str]) -> dict[str, dict[str, Any]]:
    mg = mygene.MyGeneInfo()
    out: dict[str, dict[str, Any]] = {}
    if not symbols:
        return out
    for i in range(0, len(symbols), 200):
        batch = symbols[i : i + 200]
        res = mg.querymany(
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
