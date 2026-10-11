from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from tqdm import tqdm

from src.lib.http_client import make_http_client

from src.lib.models import DiseaseHit
from src.lib.settings import load_config


SEARCH_QUERY = """
query SearchDiseases($q: String!, $size: Int!) {
  search(queryString: $q, entityNames: ["disease"], page: { index: 0, size: $size }) {
    hits {
      id
      name
      entity
      description
    }
  }
}
"""

DISEASE_HEADER_QUERY = """
query DiseaseHeader($efoId: String!) {
  disease(efoId: $efoId) {
    id
    name
  }
}
"""

ASSOCIATIONS_QUERY = """
query DiseaseAssociations($efoId: String!, $index: Int!, $size: Int!) {
  disease(efoId: $efoId) {
    id
    name
    associatedTargets(page: { index: $index, size: $size }) {
      count
      rows {
        score
        target {
          id
          approvedSymbol
        }
      }
    }
  }
}
"""


def _graphql(client: httpx.Client, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    url = load_config().open_targets.graphql_url
    resp = client.post(url, json={"query": query, "variables": variables}, timeout=120.0)
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload and payload["errors"]:
        raise RuntimeError(f"Open Targets GraphQL errors: {payload['errors']}")
    return payload["data"]


def fetch_disease_header(disease_ot_id: str, *, client: httpx.Client | None = None) -> DiseaseHit:
    own = client is None
    if own:
        client = make_http_client()
    assert client is not None
    try:
        data = _graphql(client, DISEASE_HEADER_QUERY, {"efoId": disease_ot_id})
        block = data.get("disease") or {}
        if not block.get("id"):
            raise ValueError(f"Unknown Open Targets disease id: {disease_ot_id!r}")
        return DiseaseHit(
            id=block["id"],
            name=block.get("name") or block["id"],
            entity="disease",
            description=None,
        )
    finally:
        if own:
            client.close()


def search_diseases(query: str, *, client: httpx.Client | None = None) -> list[DiseaseHit]:
    own = client is None
    if own:
        client = make_http_client()
    assert client is not None
    try:
        max_hits = load_config().open_targets.search.max_hits
        data = _graphql(client, SEARCH_QUERY, {"q": query, "size": max_hits})
        hits = data.get("search", {}).get("hits") or []
        out: list[DiseaseHit] = [] 
        for h in hits:
            out.append(
                DiseaseHit(
                    id=h["id"],
                    name=h.get("name") or h["id"],
                    entity=h.get("entity") or "disease",
                    description=h.get("description"),
                )
            )
        return out
    finally:
        if own:
            client.close()


def iter_associated_targets(
    disease_ot_id: str,
    *,
    client: httpx.Client | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Paginate disease–target association rows from Open Targets.

    Returns (disease_header, rows) where disease_header has id/name and rows are raw OT rows.
    """
    cfg = load_config().open_targets.associations
    page_size = min(cfg.page_size, 500)
    own = client is None
    if own:
        client = make_http_client()
    assert client is not None
    all_rows: list[dict[str, Any]] = []
    disease_meta: dict[str, Any] = {}
    index = 0
    total_count: int | None = None
    pbar: tqdm | None = None
    try:
        while True:
            data = _graphql(
                client,
                ASSOCIATIONS_QUERY,
                {"efoId": disease_ot_id, "index": index, "size": page_size},
            )
            block = data.get("disease") or {}
            if not block:
                break
            disease_meta = {"id": block.get("id"), "name": block.get("name")}
            assoc = block.get("associatedTargets") or {}
            if total_count is None:
                total_count = int(assoc.get("count") or 0)
                cap = total_count
                if cfg.max_rows is not None:
                    cap = min(cap, cfg.max_rows)
                n_pages = max(1, (cap + page_size - 1) // page_size)
                pbar = tqdm(total=n_pages, desc="Open Targets pages", unit="page")
            rows = assoc.get("rows") or []
            if not rows:
                break
            all_rows.extend(rows)
            if pbar is not None:
                pbar.update(1)
            if cfg.max_rows is not None and len(all_rows) >= cfg.max_rows:
                all_rows = all_rows[: cfg.max_rows]
                break
            if len(rows) < page_size:
                break
            if total_count and len(all_rows) >= total_count:
                break
            index += 1
        return disease_meta, all_rows
    finally:
        if pbar is not None:
            pbar.close()
        if own:
            client.close()


def cache_raw_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
