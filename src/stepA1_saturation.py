"""
Track A / Step A1 — target saturation (crowdedness) analysis.

Input:
  outputs/<run_id>/artifacts/known_disease_genes.csv
  outputs/<run_id>/manifest.json

Output:
  outputs/<run_id>/artifacts/track_a/stepA1_saturation.csv
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import httpx
import pandas as pd
from tqdm import tqdm

from src.lib.http_client import make_http_client

from src.lib.paths import manifest_path, raw_dir, run_dir
from src.lib.run_manifest import read_manifest
from src.lib.settings import load_config
from src.lib.track_a.paths import step_a1_path
from src.lib.track_a.scoring import minmax, safe_float, weighted_sum
from src.lib.track_a.sources import europepmc_hit_count, fetch_target_profile


def _load_known_targets(run_id: str) -> pd.DataFrame:
    path = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    if not path.is_file():
        raise FileNotFoundError(f"Expected merged targets file not found: {path}")
    df = pd.read_csv(path)
    if "association_score" not in df.columns:
        raise ValueError("known_disease_genes.csv missing association_score column")
    # Track A = known disease-linked targets; keep rows with DB association score.
    df = df[df["association_score"].notna()].copy()
    if df.empty:
        raise ValueError("No known targets (association_score rows) found for Track A")
    df = df.sort_values("association_score", ascending=False)
    # Dedup by ensembl id (fallback: symbol)
    key = df["ensembl_gene_id"].fillna("sym:" + df["gene_symbol"].fillna("").str.upper())
    df = df.loc[~key.duplicated()].copy()
    return df


def _has_any(flags: dict[str, bool], suffix: str) -> bool:
    sfx = suffix.lower().replace(" ", "_")
    for k, v in flags.items():
        if k.endswith(sfx) and bool(v):
            return True
    return False


def run_step_a1(run_id: str) -> Path:
    cfg = load_config().track_a
    m = read_manifest(manifest_path(run_id))
    disease_label = m.input.disease_label

    df = _load_known_targets(run_id)
    top_n = max(1, int(cfg.top_n_for_analysis))
    df = df.head(top_n).copy()

    recs: list[dict] = []
    raw_profiles: dict[str, dict] = {}
    with make_http_client() as client:
        for _, r in tqdm(df.iterrows(), total=len(df), desc="A1 saturation"):
            gene_symbol = str(r.get("gene_symbol") or "").strip()
            ensembl = str(r.get("ensembl_gene_id") or "").strip()
            if not gene_symbol:
                continue

            pub_count = europepmc_hit_count(
                client, disease_label=disease_label, gene_symbol=gene_symbol
            )

            profile = {}
            flags: dict[str, bool] = {}
            uniprot_swissprot_count = 0
            if ensembl:
                try:
                    profile = fetch_target_profile(client, ensembl_id=ensembl)
                    flags = profile.get("tractability_flags", {}) or {}
                    raw_profiles[ensembl] = profile
                    prot_ids = profile.get("protein_ids") or []
                    uniprot_swissprot_count = sum(
                        1 for p in prot_ids if str((p or {}).get("source")) == "uniprot_swissprot"
                    )
                except Exception:
                    # Non-fatal: keep working with literature/publication evidence.
                    flags = {}

            approved_drug_flag = _has_any(flags, "approved_drug")
            clinical_flag = _has_any(flags, "advanced_clinical") or _has_any(
                flags, "phase_1_clinical"
            )
            ligand_flag = bool(flags.get("sm:high-quality_ligand", False)) or bool(
                flags.get("sm:structure_with_ligand", False)
            )

            recs.append(
                {
                    "gene_symbol": gene_symbol,
                    "ensembl_gene_id": ensembl or None,
                    "association_score": safe_float(r.get("association_score"), 0.0),
                    "publication_count": int(pub_count),
                    "approved_drug_flag": int(approved_drug_flag),
                    "clinical_flag": int(clinical_flag),
                    "ligand_flag": int(ligand_flag),
                    "uniprot_swissprot_count": int(uniprot_swissprot_count),
                }
            )

    out = pd.DataFrame.from_records(recs)
    if out.empty:
        raise ValueError("Track A step A1 produced no rows")

    out["publication_count_log"] = out["publication_count"].apply(lambda x: math.log1p(safe_float(x)))
    pub_norm = minmax(out["publication_count_log"].tolist())
    out["publication_count_norm"] = pub_norm

    w = cfg.crowdedness_weights
    crowded_scores = []
    for _, row in out.iterrows():
        crowded_scores.append(
            weighted_sum(
                {
                    "publication_count": safe_float(row["publication_count_norm"]),
                    "approved_drug_flag": safe_float(row["approved_drug_flag"]),
                    "clinical_flag": safe_float(row["clinical_flag"]),
                    "ligand_flag": safe_float(row["ligand_flag"]),
                },
                w,
            )
        )
    out["crowded_score"] = crowded_scores
    out = out.sort_values("crowded_score", ascending=False)

    out_path = step_a1_path(run_id)
    out.to_csv(out_path, index=False)

    raw_dir_path = raw_dir(run_id)
    raw_dir_path.mkdir(parents=True, exist_ok=True)
    (raw_dir_path / "track_a_target_profiles.json").write_text(
        json.dumps(raw_profiles, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track A Step A1 — saturation / crowdedness")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_a1(args.run_id)


if __name__ == "__main__":
    main()
