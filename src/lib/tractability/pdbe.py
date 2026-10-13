"""PDBe experimental structure lookup by UniProt accession."""

from __future__ import annotations

from typing import Any

import httpx

PDBE_BEST = "https://www.ebi.ac.uk/pdbe/api/mappings/best_structures/{accession}"


def uniprot_accessions_from_profile(profile: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for p in profile.get("protein_ids") or []:
        if str((p or {}).get("source") or "") == "uniprot_swissprot":
            acc = str((p or {}).get("id") or "").strip()
            if acc and acc not in out:
                out.append(acc)
    return out


def pdbe_has_experimental_structure(
    client: httpx.Client, uniprot_accession: str
) -> bool:
    """Return True if PDBe reports at least one experimental structure mapping."""
    acc = uniprot_accession.strip()
    if not acc:
        return False
    try:
        r = client.get(PDBE_BEST.format(accession=acc), timeout=60.0)
        if r.status_code == 404:
            return False
        r.raise_for_status()
        data = r.json() or {}
        hits = data.get(acc) or data.get(acc.upper()) or []
        return bool(hits)
    except Exception:
        return False


def boost_structure_with_pdbe(
    structure_score: float, *, has_pdb: bool | None
) -> float:
    if has_pdb is True:
        return max(structure_score, 0.9)
    return structure_score
