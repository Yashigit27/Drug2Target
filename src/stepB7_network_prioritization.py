"""
Track B / B7 — network prioritization.

Each candidate is placed on the real STRING map of known disease genes
and candidates. The main score is how strongly it links to that whole
group. A smaller part rewards a candidate that sits on a shortest path
between known genes that are not already linked to each other.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import networkx as nx
import pandas as pd

from src.lib.http_client import make_http_client
from src.lib.paths import run_dir
from src.lib.settings import load_config
from src.lib.track_b.paths import step_b1_edges_path, step_b1_path, step_b7_path
from src.lib.track_b.scoring import minmax
from src.lib.track_b.sources import string_network_edges
from src.lib.track_b.string_background import apply_hub_correction, resolve_db_path

DISTANCE_WEIGHT = 0.75
BRIDGE_WEIGHT = 0.25


def _clean_symbol(value: object) -> str:
    sym = str(value).strip()
    if not sym or sym.lower() == "nan":
        return ""
    return sym


def _edge(a: str, b: str) -> tuple[str, str] | None:
    left, right = a.strip().upper(), b.strip().upper()
    if not left or not right or left == right:
        return None
    return tuple(sorted((left, right)))


def _unit_score(value: object) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    if score != score:
        return 0.0
    if score > 1:
        score = score / 1000.0
    if score < 0:
        return 0.0
    return min(score, 1.0)


def _add_link(links: dict[tuple[str, str], float], a: str, b: str, score: float) -> None:
    pair = _edge(a, b)
    if pair is None:
        return
    links[pair] = max(links.get(pair, 0.0), _unit_score(score))


def score_network(
    seeds: list[str],
    candidates: list[str],
    links: dict[tuple[str, str], float],
) -> pd.DataFrame:
    """Rank candidates by link strength to the seeds, plus a bridge bonus."""
    seed_ids = []
    seen_seeds: set[str] = set()
    for raw in seeds:
        sym = _clean_symbol(raw)
        key = sym.upper()
        if not sym or key in seen_seeds:
            continue
        seen_seeds.add(key)
        seed_ids.append(key)
    if not seed_ids:
        raise ValueError("B7 needs at least one disease seed gene")

    rows: list[tuple[str, str]] = []
    seen_candidates: set[str] = set()
    for raw in candidates:
        sym = _clean_symbol(raw)
        key = sym.upper()
        if not sym or key in seen_candidates or key in seen_seeds:
            continue
        seen_candidates.add(key)
        rows.append((sym, key))
    if not rows:
        raise ValueError("B7 has no candidates to score")

    nodes = set(seed_ids) | {key for _, key in rows}
    G = nx.Graph()
    G.add_nodes_from(nodes)
    for (left, right), score in links.items():
        if left in nodes and right in nodes:
            G.add_edge(left, right, score=score)

    dist_from_seed = {
        seed: nx.single_source_shortest_path_length(G, seed) for seed in seed_ids if seed in G
    }
    finite = [hop for dist in dist_from_seed.values() for hop in dist.values() if hop > 0]
    missing = (max(finite) if finite else 0) + 1

    means: list[float] = []
    strengths: list[float] = []
    for _, key in rows:
        hops = [dist_from_seed.get(seed, {}).get(key, missing) for seed in seed_ids]
        means.append(sum(hops) / len(hops))
        held = 0.0
        for seed in seed_ids:
            held += float(G[key][seed]["score"]) if G.has_edge(key, seed) else 0.0
        strengths.append(held / len(seed_ids))

    seeds_in_graph = [seed for seed in seed_ids if seed in G]
    bridge = {key: 0.0 for _, key in rows}
    if len(seeds_in_graph) >= 2:
        raw_bridge = nx.betweenness_centrality_subset(
            G,
            sources=seeds_in_graph,
            targets=seeds_in_graph,
            normalized=True,
        )
        for _, key in rows:
            bridge[key] = float(raw_bridge.get(key, 0.0))

    bridge_norm = minmax([bridge[key] for _, key in rows])
    scores = [
        DISTANCE_WEIGHT * strength + BRIDGE_WEIGHT * bridge_score
        for strength, bridge_score in zip(strengths, bridge_norm, strict=False)
    ]
    out = pd.DataFrame(
        {
            "candidate_gene_symbol": [sym for sym, _ in rows],
            "mean_distance_to_seeds": means,
            "mean_link_strength": strengths,
            "betweenness": [bridge[key] for _, key in rows],
            "network_prioritization_score": scores,
        }
    )
    return out.sort_values(
        ["network_prioritization_score", "mean_link_strength", "mean_distance_to_seeds"],
        ascending=[False, False, True],
    )


def _disease_seeds(run_id: str, fallback: list[str]) -> list[str]:
    """Known disease genes B1 started from. Fall back to seeds still in the B1 edges."""
    path = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    if not path.is_file():
        return fallback
    frame = pd.read_csv(path)
    if "gene_symbol" not in frame.columns:
        return fallback
    if "association_score" in frame.columns:
        frame = frame[frame["association_score"].notna()].sort_values("association_score", ascending=False)
    limit = max(1, int(load_config().track_b.seed_top_n))
    seeds = []
    seen: set[str] = set()
    for value in frame["gene_symbol"].head(limit):
        sym = _clean_symbol(value)
        if sym and sym.upper() not in seen:
            seen.add(sym.upper())
            seeds.append(sym)
    return seeds or fallback


def run_step_b7(run_id: str) -> Path:
    neighbors_path = step_b1_path(run_id)
    edges_path = step_b1_edges_path(run_id)
    if not neighbors_path.is_file() or not edges_path.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {neighbors_path} or {edges_path}")

    neighbors = pd.read_csv(neighbors_path)
    b1_edges = pd.read_csv(edges_path)
    if neighbors.empty or b1_edges.empty:
        raise ValueError("B1 output is empty")
    for frame, column in (
        (neighbors, "candidate_gene_symbol"),
        (b1_edges, "seed_gene_symbol"),
        (b1_edges, "candidate_gene_symbol"),
    ):
        if column not in frame.columns:
            raise ValueError(f"B1 file is missing column {column}")

    candidates = [_clean_symbol(v) for v in neighbors["candidate_gene_symbol"]]
    kept = {sym.upper() for sym in candidates if sym}
    seeds: list[str] = []
    seen_seeds: set[str] = set()
    links: dict[tuple[str, str], float] = {}
    for _, row in b1_edges.iterrows():
        seed = _clean_symbol(row["seed_gene_symbol"])
        cand = _clean_symbol(row["candidate_gene_symbol"])
        if not seed or not cand or cand.upper() not in kept:
            continue
        if seed.upper() not in seen_seeds:
            seen_seeds.add(seed.upper())
            seeds.append(seed)
        _add_link(links, seed, cand, row.get("string_score"))

    cfg = load_config().track_b
    try:
        with make_http_client() as client:
            extra = string_network_edges(
                client,
                seeds + [sym for sym in candidates if sym],
                required_score=int(cfg.string_required_score),
            )
        allowed = {seed.upper() for seed in seeds} | kept
        for left, right, score in extra:
            if left in allowed and right in allowed:
                _add_link(links, left, right, score)
    except Exception as exc:
        print(f"B7 STRING network lookup failed, using B1 links only: {exc}")

    out = score_network(seeds, candidates, links)
    b7_cfg = load_config().track_b.b7
    out = apply_hub_correction(
        out,
        _disease_seeds(run_id, seeds),
        resolve_db_path(b7_cfg.string_db),
        n_random=int(b7_cfg.n_random),
        degree_window=float(b7_cfg.degree_window),
    )
    out_path = step_b7_path(run_id)
    out.to_csv(out_path, index=False)
    bridges = int((out["betweenness"] > 0).sum())
    z_note = ""
    if out["proximity_z"].notna().any():
        z_note = (
            f", specificity z {out['proximity_z'].min():.2f}"
            f"-{out['proximity_z'].max():.2f}"
        )
    print(
        f"wrote {out_path} ({len(out)} rows, "
        f"link strength {out['mean_link_strength'].min():.2f}"
        f"-{out['mean_link_strength'].max():.2f}{z_note}, "
        f"on a disease-gene path {bridges}/{len(out)})"
    )
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B7 — network prioritization")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b7(args.run_id)


if __name__ == "__main__":
    main()
