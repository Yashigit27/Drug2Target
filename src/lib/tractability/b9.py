"""Orchestrate B9 readiness scoring (defaults / OT / hybrid+PDBe)."""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
from tqdm import tqdm

from src.lib.expression.gtex_lookup import symbols_to_ensembl
from src.lib.http_client import make_http_client
from src.lib.settings import B9TractabilityConfig, load_config
from src.lib.track_a.sources import fetch_target_profile
from src.lib.tractability.defaults import (
    DEFAULT_DRUGGABILITY,
    DEFAULT_SAFETY,
    DEFAULT_STRUCTURE,
    default_readiness_score,
    score_defaults,
)
from src.lib.tractability.pdbe import (
    boost_structure_with_pdbe,
    pdbe_has_experimental_structure,
    uniprot_accessions_from_profile,
)
from src.lib.tractability.scoring import combine_readiness, scores_from_ot_profile


def score_b9_readiness(
    b1: pd.DataFrame,
    *,
    cfg: B9TractabilityConfig | None = None,
) -> pd.DataFrame:
    """
    Always returns columns consumed by B10:
      candidate_gene_symbol, b9_readiness_score
    plus structure/druggability/safety breakdown and provenance.
    """
    if b1.empty:
        raise ValueError("B1 output empty")
    if "candidate_gene_symbol" not in b1.columns:
        raise ValueError("B1 missing candidate_gene_symbol")

    cfg = cfg or load_config().track_b.b9
    provider = (cfg.provider or "hybrid").strip().lower()
    symbols = (
        b1["candidate_gene_symbol"]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: s != ""]
        .drop_duplicates()
        .tolist()
    )
    symbols = symbols[: max(1, int(cfg.max_genes))]

    if provider == "defaults":
        return score_defaults(symbols)

    try:
        return _score_ot_hybrid(symbols, cfg=cfg, provider=provider)
    except Exception as exc:
        print(f"B9: OT/hybrid failed ({exc}); falling back to defaults")
        return score_defaults(symbols)


def _score_ot_hybrid(
    symbols: list[str],
    *,
    cfg: B9TractabilityConfig,
    provider: str,
) -> pd.DataFrame:
    ens_map = symbols_to_ensembl(symbols)
    use_pdbe = bool(cfg.use_pdbe) and provider == "hybrid"
    rows: list[dict[str, Any]] = []
    ot_ok = 0
    pdbe_hits = 0

    with make_http_client() as client:
        for sym in tqdm(symbols, desc="B9 tractability"):
            ens = ens_map.get(sym.upper())
            if not ens:
                rows.append(_fallback_row(sym, reason="no_ensembl"))
                continue
            try:
                profile = fetch_target_profile(client, ensembl_id=ens)
            except Exception:
                # brief backoff then one retry
                time.sleep(1.0)
                try:
                    profile = fetch_target_profile(client, ensembl_id=ens)
                except Exception:
                    rows.append(_fallback_row(sym, reason="ot_error", ensembl=ens))
                    continue

            ot_ok += 1
            scored = scores_from_ot_profile(profile)
            structure = float(scored["structure_availability_score"])
            has_pdb: bool | None = None
            uniprot_acc = None
            if use_pdbe:
                accessions = uniprot_accessions_from_profile(profile)
                uniprot_acc = accessions[0] if accessions else None
                if uniprot_acc:
                    has_pdb = pdbe_has_experimental_structure(client, uniprot_acc)
                    if has_pdb:
                        pdbe_hits += 1
                    structure = boost_structure_with_pdbe(structure, has_pdb=has_pdb)

            readiness = combine_readiness(
                structure,
                float(scored["druggability_score"]),
                float(scored["safety_score"]),
                w_struct=cfg.structure_weight,
                w_drug=cfg.druggability_weight,
                w_safety=cfg.safety_weight,
            )
            method = "hybrid" if use_pdbe else "ot_tractability"
            rows.append(
                {
                    "candidate_gene_symbol": sym,
                    "ensembl_gene_id": ens,
                    "uniprot_accession": uniprot_acc,
                    "structure_availability_score": round(structure, 4),
                    "druggability_score": scored["druggability_score"],
                    "safety_score": scored["safety_score"],
                    "b9_readiness_score": readiness,
                    "ot_approved_drug_flag": scored["ot_approved_drug_flag"],
                    "ot_structure_with_ligand_flag": scored["ot_structure_with_ligand_flag"],
                    "chemical_probe_count": scored["chemical_probe_count"],
                    "safety_liability_count": scored["safety_liability_count"],
                    "is_essential": scored["is_essential"],
                    "lof_oe": scored["lof_oe"],
                    "pdbe_experimental_structure": has_pdb,
                    "b9_method": method,
                }
            )

    out = pd.DataFrame.from_records(rows)
    print(
        f"B9: provider={provider} ot_ok={ot_ok}/{len(symbols)} "
        f"pdbe_hits={pdbe_hits if use_pdbe else 'skipped'}"
    )
    return out.sort_values("b9_readiness_score", ascending=False).reset_index(drop=True)


def _fallback_row(
    symbol: str, *, reason: str, ensembl: str | None = None
) -> dict[str, Any]:
    return {
        "candidate_gene_symbol": symbol,
        "ensembl_gene_id": ensembl,
        "uniprot_accession": None,
        "structure_availability_score": DEFAULT_STRUCTURE,
        "druggability_score": DEFAULT_DRUGGABILITY,
        "safety_score": DEFAULT_SAFETY,
        "b9_readiness_score": default_readiness_score(),
        "ot_approved_drug_flag": 0,
        "ot_structure_with_ligand_flag": 0,
        "chemical_probe_count": 0,
        "safety_liability_count": 0,
        "is_essential": None,
        "lof_oe": None,
        "pdbe_experimental_structure": None,
        "b9_method": f"defaults_fallback:{reason}",
    }
