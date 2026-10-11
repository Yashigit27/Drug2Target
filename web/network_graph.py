"""Network graph JSON for visualization (STRING seed expansion edges)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.lib.paths import run_dir
from src.lib.track_b.paths import step_b1_edges_path, step_b1_path


def build_network_graph(run_id: str, *, top_n: int = 40) -> dict[str, Any]:
    base = run_dir(run_id)
    if not base.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")

    edges_path = step_b1_edges_path(run_id)
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    if edges_path.is_file():
        df = pd.read_csv(edges_path)
        if not df.empty:
            cand_counts = df["candidate_gene_symbol"].astype(str).str.upper().value_counts()
            keep = set(cand_counts.head(top_n).index.tolist())
            for _, r in df.iterrows():
                seed = str(r.get("seed_gene_symbol") or "").upper()
                cand = str(r.get("candidate_gene_symbol") or "").upper()
                if cand not in keep:
                    continue
                nodes.setdefault(seed, {"id": seed, "label": seed, "group": "seed"})
                nodes.setdefault(cand, {"id": cand, "label": cand, "group": "candidate"})
                edges.append(
                    {
                        "source": seed,
                        "target": cand,
                        "weight": float(r.get("string_score") or 0.0),
                        "source_db": r.get("source_db", "STRING"),
                    }
                )
    else:
        agg_path = step_b1_path(run_id)
        if not agg_path.is_file():
            raise FileNotFoundError("No B1 network artifacts found.")
        agg = pd.read_csv(agg_path).head(top_n)
        for _, r in agg.iterrows():
            cand = str(r.get("candidate_gene_symbol") or "").upper()
            nodes[cand] = {
                "id": cand,
                "label": cand,
                "group": "candidate",
                "seed_count": int(r.get("seed_count") or 0),
            }

    return {
        "run_id": run_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": edges,
    }
