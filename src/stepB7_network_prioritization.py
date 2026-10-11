"""
Track B / B7 — Network prioritization (proximity + centrality).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import pandas as pd

from src.lib.track_b.paths import step_b1_path, step_b7_path
from src.lib.track_b.scoring import minmax


def run_step_b7(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    # Reconstruct bipartite-like edges by expanding from aggregated B1 file (seed info not retained),
    # use candidate as nodes connected to synthetic disease module hub.
    b1 = pd.read_csv(p1)
    if b1.empty:
        raise ValueError("B1 output empty")
    G = nx.Graph()
    hub = "__disease_module__"
    G.add_node(hub)
    for _, r in b1.iterrows():
        c = str(r["candidate_gene_symbol"])
        w = float(r.get("mean_string_score") or 0.0)
        G.add_edge(hub, c, weight=w)

    bet = nx.betweenness_centrality(G, normalized=True)
    clo = nx.closeness_centrality(G)

    recs = []
    for _, r in b1.iterrows():
        c = str(r["candidate_gene_symbol"])
        recs.append(
            {
                "candidate_gene_symbol": c,
                "proximity_to_seed": float(r.get("seed_count") or 0.0),
                "betweenness": float(bet.get(c, 0.0)),
                "closeness": float(clo.get(c, 0.0)),
            }
        )
    out = pd.DataFrame.from_records(recs).drop_duplicates(subset=["candidate_gene_symbol"])
    p_norm = minmax(out["proximity_to_seed"].tolist())
    b_norm = minmax(out["betweenness"].tolist())
    c_norm = minmax(out["closeness"].tolist())
    out["network_prioritization_score"] = [
        0.5 * p + 0.25 * b + 0.25 * c for p, b, c in zip(p_norm, b_norm, c_norm, strict=False)
    ]
    out = out.sort_values("network_prioritization_score", ascending=False)
    out_path = step_b7_path(run_id)
    out.to_csv(out_path, index=False)
    print(f"wrote {out_path} ({len(out)} rows)")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B7 — network prioritization")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b7(args.run_id)


if __name__ == "__main__":
    main()
