"""
Track B / B4 — Differential expression evidence proxy.

Uses literature hit counts for disease+gene+(up/down regulated terms).
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
from src.lib.track_b.paths import step_b1_path, step_b4_path

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def _de_hit_count(client: httpx.Client, disease: str, gene: str) -> int:
    q = (
        f'ABSTRACT:"{disease}" AND {gene} '
        f'AND ("upregulated" OR "downregulated" OR "overexpression" OR "underexpression")'
    )
    r = client.get(EPMC, params={"query": q, "format": "json", "pageSize": 1}, timeout=60.0)
    r.raise_for_status()
    return int((r.json() or {}).get("hitCount") or 0)


def run_step_b4(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    m = read_manifest(manifest_path(run_id))
    disease = m.input.disease_label

    recs = []
    with make_http_client() as client:
        for g in tqdm(
            b1["candidate_gene_symbol"].dropna().astype(str).tolist(), desc="B4 DE evidence"
        ):
            c = _de_hit_count(client, disease, g)
            recs.append({"candidate_gene_symbol": g, "de_literature_count": c})
    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    if out.empty:
        raise ValueError("B4 produced no rows")
    logv = [math.log1p(float(x)) for x in out["de_literature_count"].tolist()]
    lo, hi = min(logv), max(logv)
    if hi <= lo:
        out["differential_expression_score"] = 0.0
    else:
        out["differential_expression_score"] = [(v - lo) / (hi - lo) for v in logv]
    out = out.sort_values("differential_expression_score", ascending=False)
    out_path = step_b4_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B4 — differential expression proxy")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b4(args.run_id)


if __name__ == "__main__":
    main()
