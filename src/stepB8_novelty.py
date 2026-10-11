"""
Track B / B8 — novelty filter.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import httpx
import pandas as pd
from tqdm import tqdm

from src.lib.http_client import make_http_client

from src.lib.paths import manifest_path
from src.lib.run_manifest import read_manifest
from src.lib.track_a.sources import europepmc_hit_count, fetch_target_profile
from src.lib.track_b.paths import step_b1_path, step_b8_path


def run_step_b8(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    m = read_manifest(manifest_path(run_id))
    disease = m.input.disease_label

    recs = []
    with make_http_client() as client:
        for g in tqdm(
            b1["candidate_gene_symbol"].dropna().astype(str).tolist(), desc="B8 novelty"
        ):
            pub = europepmc_hit_count(client, disease_label=disease, gene_symbol=g)
            approved = 0
            clinical = 0
            # we do not always have ensembl for candidates; leave these conservative.
            recs.append(
                {
                    "candidate_gene_symbol": g,
                    "disease_publication_count": int(pub),
                    "approved_drug_flag": approved,
                    "clinical_flag": clinical,
                }
            )
    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    if out.empty:
        raise ValueError("B8 produced no rows")
    logs = [math.log1p(float(x)) for x in out["disease_publication_count"].tolist()]
    lo, hi = min(logs), max(logs)
    pub_norm = [0.0 if hi <= lo else (v - lo) / (hi - lo) for v in logs]
    out["publication_crowdedness_norm"] = pub_norm
    out["novelty_score"] = [
        1.0 - min(1.0, p + 0.25 * a + 0.25 * c)
        for p, a, c in zip(
            out["publication_crowdedness_norm"].tolist(),
            out["approved_drug_flag"].tolist(),
            out["clinical_flag"].tolist(),
            strict=False,
        )
    ]
    out = out.sort_values("novelty_score", ascending=False)
    out_path = step_b8_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B8 — novelty")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b8(args.run_id)


if __name__ == "__main__":
    main()
