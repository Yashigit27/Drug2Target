"""Saved human STRING network for the B7 hub check.

A candidate should stay high only when its links to this disease's known
genes are stronger than ordinary proteins with a similar number of partners.
The ordinary proteins come from one local STRING database, built once.
"""

from __future__ import annotations

import gzip
import math
import random
import sqlite3
from pathlib import Path

import httpx
import pandas as pd

from src.lib.paths import repo_root
from src.lib.track_b.scoring import minmax

LINKS_URL = (
    "https://stringdb-static.org/download/protein.links.v12.0/"
    "9606.protein.links.v12.0.txt.gz"
)
INFO_URL = (
    "https://stringdb-static.org/download/protein.info.v12.0/"
    "9606.protein.info.v12.0.txt.gz"
)
DISTANCE_WEIGHT = 0.75
BRIDGE_WEIGHT = 0.25


def resolve_db_path(rel_or_abs: str) -> Path:
    path = Path(rel_or_abs)
    if not path.is_absolute():
        path = repo_root() / path
    return path


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"already downloaded {dest.name}")
        return
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url, timeout=None) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 1024):
                handle.write(chunk)
    tmp.replace(dest)
    print(f"saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")


def _symbols(info_gz: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with gzip.open(info_gz, "rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 2:
                continue
            protein, name = parts[0].strip(), parts[1].strip().upper()
            if protein and name and name != "PREFERRED_NAME":
                out.setdefault(protein, name)
    return out


def build_database(db_path: Path, links_gz: Path, info_gz: Path, min_score: int) -> None:
    """Turn STRING files into gene, partner, score plus a partner count."""
    names = _symbols(info_gz)
    print(f"STRING symbols {len(names)}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.is_file():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(
            """
            CREATE TABLE links (
                gene TEXT NOT NULL,
                partner TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (gene, partner)
            )
            """
        )
        batch: list[tuple[str, str, float]] = []
        kept = 0
        with gzip.open(links_gz, "rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 3 or parts[0] == "protein1":
                    continue
                try:
                    combined = int(float(parts[2]))
                except ValueError:
                    continue
                if combined < min_score:
                    continue
                left = names.get(parts[0])
                right = names.get(parts[1])
                if not left or not right or left == right:
                    continue
                score = combined / 1000.0
                batch.append((left, right, score))
                batch.append((right, left, score))
                kept += 1
                if len(batch) >= 50000:
                    _insert_links(conn, batch)
                    batch.clear()
        if batch:
            _insert_links(conn, batch)
        print(f"undirected links kept {kept}")
        conn.execute(
            """
            CREATE TABLE degree (
                gene TEXT PRIMARY KEY,
                n_partners INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO degree (gene, n_partners)
            SELECT gene, COUNT(*) FROM links GROUP BY gene
            """
        )
        conn.execute("CREATE INDEX idx_links_gene ON links(gene)")
        conn.commit()
    finally:
        conn.close()
    print(f"wrote {db_path}")


def _insert_links(conn: sqlite3.Connection, rows: list[tuple[str, str, float]]) -> None:
    conn.executemany(
        """
        INSERT INTO links (gene, partner, score) VALUES (?, ?, ?)
        ON CONFLICT(gene, partner) DO UPDATE SET
            score = MAX(links.score, excluded.score)
        """,
        rows,
    )
    conn.commit()


def download_and_build(db_path: Path, min_score: int = 400) -> Path:
    raw = db_path.parent / "raw"
    links = raw / "9606.protein.links.v12.0.txt.gz"
    info = raw / "9606.protein.info.v12.0.txt.gz"
    from src.lib.http_client import make_http_client

    with make_http_client(follow_redirects=True) as client:
        _download(client, INFO_URL, info)
        _download(client, LINKS_URL, links)
    build_database(db_path, links, info, min_score)
    return db_path


class HumanStringNetwork:
    def __init__(self, db_path: Path) -> None:
        self.conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        self.degrees = {
            str(gene): int(count)
            for gene, count in self.conn.execute("SELECT gene, n_partners FROM degree")
        }

    def close(self) -> None:
        self.conn.close()

    def specificity(
        self,
        candidates: list[str],
        seeds: list[str],
        *,
        n_random: int = 100,
        degree_window: float = 0.2,
    ) -> dict[str, tuple[float, int, float]]:
        """Return gene -> (z, partner count, mean link strength on this network)."""
        seed_ids = []
        seen: set[str] = set()
        for raw in seeds:
            key = str(raw).strip().upper()
            if key and key not in seen:
                seen.add(key)
                seed_ids.append(key)
        if not seed_ids:
            return {}
        touched: dict[str, dict[str, float]] = {}
        for seed in seed_ids:
            for partner, score in self.conn.execute(
                "SELECT partner, score FROM links WHERE gene = ?",
                (seed,),
            ):
                touched.setdefault(str(partner), {})[seed] = float(score)

        def strength(gene: str) -> float:
            held = touched.get(gene, {})
            return sum(held.get(seed, 0.0) for seed in seed_ids) / len(seed_ids)

        cand_ids = []
        cand_seen: set[str] = set()
        for raw in candidates:
            key = str(raw).strip().upper()
            if key and key not in cand_seen and key not in seen:
                cand_seen.add(key)
                cand_ids.append(key)
        pool = [(gene, degree) for gene, degree in self.degrees.items() if gene not in seen and gene not in cand_seen]
        pool.sort(key=lambda item: item[1])
        degree_values = [degree for _, degree in pool]

        out: dict[str, tuple[float, int, float]] = {}
        for gene in cand_ids:
            degree = self.degrees.get(gene, 0)
            observed = strength(gene)
            chosen = _degree_matched(pool, degree_values, degree, n_random, degree_window, gene)
            out[gene] = (_zscore(observed, [strength(item) for item in chosen]), degree, observed)
        return out


def _degree_matched(
    pool: list[tuple[str, int]],
    degree_values: list[int],
    degree: int,
    n_random: int,
    window: float,
    gene: str,
) -> list[str]:
    if not pool:
        return []
    span = window
    chosen: list[str] = []
    while True:
        if degree <= 0:
            low, high = 0, 0 if span <= window else max(1, math.ceil(span * 10))
        else:
            low = max(0, math.floor(degree * (1.0 - span)))
            high = max(low, math.ceil(degree * (1.0 + span)))
        left = _lower(degree_values, low)
        right = _upper(degree_values, high)
        chosen = [name for name, _deg in pool[left:right]]
        if len(chosen) >= n_random or span >= 2.0:
            break
        span += 0.2
    if not chosen:
        return []
    rng = random.Random(gene)
    if len(chosen) > n_random:
        chosen = rng.sample(chosen, n_random)
    return chosen


def _lower(values: list[int], target: int) -> int:
    lo, hi = 0, len(values)
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _upper(values: list[int], target: int) -> int:
    lo, hi = 0, len(values)
    while lo < hi:
        mid = (lo + hi) // 2
        if values[mid] <= target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _zscore(observed: float, random_values: list[float]) -> float:
    if len(random_values) < 2:
        return 0.0
    mean = sum(random_values) / len(random_values)
    spread = math.sqrt(sum((value - mean) ** 2 for value in random_values) / (len(random_values) - 1))
    if spread < 1e-8:
        if abs(observed - mean) < 1e-8:
            return 0.0
        return 50.0 if observed > mean else -50.0
    z = (observed - mean) / spread
    if not math.isfinite(z):
        return 0.0
    return max(-50.0, min(50.0, z))


def z_to_unit(z: float) -> float:
    """Map a z-score onto 0–1. Chance (z = 0) is 0.5. Higher z stays higher."""
    if not math.isfinite(z):
        return 0.5
    squeezed = z / (1.0 + abs(z))
    return 0.5 + 0.5 * squeezed


def apply_hub_correction(
    out: pd.DataFrame,
    seeds: list[str],
    db_path: Path,
    *,
    n_random: int = 100,
    degree_window: float = 0.2,
) -> pd.DataFrame:
    """Add partner count and proximity z. Rank on z when the database exists."""
    scored = out.copy()
    if not db_path.is_file():
        print(f"B7 STRING background missing ({db_path}); hub check skipped")
        scored["string_degree"] = pd.NA
        scored["proximity_z"] = pd.NA
        return scored

    network = HumanStringNetwork(db_path)
    try:
        stats = network.specificity(
            scored["candidate_gene_symbol"].tolist(),
            seeds,
            n_random=n_random,
            degree_window=degree_window,
        )
    finally:
        network.close()

    degrees: list[int] = []
    zs: list[float] = []
    for gene in scored["candidate_gene_symbol"].tolist():
        z, degree, _observed = stats.get(str(gene).upper(), (0.0, 0, 0.0))
        degrees.append(degree)
        zs.append(z)
    bridge_norm = minmax([float(value) for value in scored["betweenness"].tolist()])
    scored["string_degree"] = degrees
    scored["proximity_z"] = zs
    scored["network_prioritization_score"] = [
        DISTANCE_WEIGHT * z_to_unit(z) + BRIDGE_WEIGHT * bridge
        for z, bridge in zip(zs, bridge_norm, strict=False)
    ]
    return scored.sort_values(
        ["network_prioritization_score", "proximity_z", "mean_link_strength"],
        ascending=[False, False, False],
    )


def main() -> None:
    import argparse

    from src.lib.settings import load_config

    parser = argparse.ArgumentParser(description="Build the human STRING background for B7")
    parser.add_argument("--min-score", type=int, default=None)
    args = parser.parse_args()
    cfg = load_config().track_b
    db_path = resolve_db_path(cfg.b7.string_db)
    min_score = int(args.min_score if args.min_score is not None else cfg.string_required_score)
    download_and_build(db_path, min_score)


if __name__ == "__main__":
    main()
