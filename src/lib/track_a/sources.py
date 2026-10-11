from __future__ import annotations

from typing import Any

import httpx

from src.lib.settings import load_config


EPMC_SEARCH = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

TARGET_PROFILE_QUERY = """
query TargetProfile($id:String!){
  target(ensemblId:$id){
    id
    approvedSymbol
    tractability { label modality value }
    proteinIds { id source }
  }
}
"""


def europepmc_hit_count(client: httpx.Client, *, disease_label: str, gene_symbol: str) -> int:
    q = f'ABSTRACT:"{disease_label}" AND {gene_symbol}'
    r = client.get(
        EPMC_SEARCH,
        params={"query": q, "format": "json", "pageSize": 1},
        timeout=60.0,
    )
    r.raise_for_status()
    j = r.json()
    return int(j.get("hitCount") or 0)


def fetch_target_profile(client: httpx.Client, *, ensembl_id: str) -> dict[str, Any]:
    url = load_config().open_targets.graphql_url
    r = client.post(
        url,
        json={"query": TARGET_PROFILE_QUERY, "variables": {"id": ensembl_id}},
        timeout=120.0,
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("errors"):
        raise RuntimeError(f"Open Targets target profile errors: {payload['errors']}")
    t = (payload.get("data") or {}).get("target") or {}
    tract = t.get("tractability") or []
    profile = {
        "target_id": t.get("id"),
        "approved_symbol": t.get("approvedSymbol"),
        "protein_ids": t.get("proteinIds") or [],
        "tractability_flags": {},
    }
    flags: dict[str, bool] = {}
    for row in tract:
        label = str(row.get("label") or "").strip().lower().replace(" ", "_")
        modality = str(row.get("modality") or "").strip().lower()
        key = f"{modality}:{label}" if modality else label
        flags[key] = bool(row.get("value"))
    profile["tractability_flags"] = flags
    return profile


def tractability_flag(flags: dict[str, bool], modality: str, label: str) -> bool:
    key = f"{modality.lower()}:{label.strip().lower().replace(' ', '_')}"
    return bool(flags.get(key, False))
