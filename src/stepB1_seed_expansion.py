"""
Track B / B1 — Seed network expansion using STRING PPI.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import httpx
import pandas as pd
from tqdm import tqdm

from src.lib.http_client import make_http_client

from src.lib.paths import run_dir
from src.lib.settings import load_config
from src.lib.track_b.paths import step_b1_edges_path, step_b1_path
from src.lib.track_b.sources import string_interaction_partners


def _load_seed_targets(run_id: str) -> pd.DataFrame:
    p = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    if not p.is_file():
        raise FileNotFoundError(f"Missing merged targets: {p}")
    df = pd.read_csv(p)
    df = df[df["association_score"].notna()].copy()
    df = df.sort_values("association_score", ascending=False)
    return df


def run_step_b1(run_id: str) -> Path:
    cfg = load_config().track_b
    seeds = _load_seed_targets(run_id)
    seeds = seeds.head(max(1, int(cfg.seed_top_n)))
    seed_symbols = [str(x).strip() for x in seeds["gene_symbol"].tolist() if str(x).strip()]
    seed_set = set(seed_symbols)

    recs: list[dict] = []
    with make_http_client() as client:
        for s in tqdm(seed_symbols, desc="B1 STRING expansion"):
            try:
                rows = string_interaction_partners(
                    client,
                    gene_symbol=s,
                    required_score=int(cfg.string_required_score),
                    limit=int(cfg.string_partners_per_seed),
                )
            except Exception:
                continue
            for r in rows:
                a = str(r.get("preferredName_A") or "").strip()
                b = str(r.get("preferredName_B") or "").strip()
                score = float(r.get("score") or 0.0)
                cand = b if a.upper() == s.upper() else a
                if not cand or cand.upper() == s.upper() or cand in seed_set:
                    continue
                recs.append(
                    {
                        "seed_gene_symbol": s,
                        "candidate_gene_symbol": cand,
                        "string_score": score,
                        "source_db": "STRING",
                    }
                )

    if not recs:
        raise ValueError("B1 produced no candidate neighbors.")
    df = pd.DataFrame.from_records(recs)
    agg = (
        df.groupby("candidate_gene_symbol", as_index=False)
        .agg(
            seed_count=("seed_gene_symbol", "nunique"),
            mean_string_score=("string_score", "mean"),
            max_string_score=("string_score", "max"),
        )
        .sort_values(["seed_count", "mean_string_score"], ascending=[False, False])
    )
    agg = agg.head(max(1, int(cfg.top_candidates_for_scoring)))
    out = agg.copy()
    out["network_support_seed"] = out["seed_count"]

    edges_path = step_b1_edges_path(run_id)
    df.to_csv(edges_path, index=False)

    out_path = step_b1_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B1 — STRING seed expansion")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b1(args.run_id)


if __name__ == "__main__":
    main()
