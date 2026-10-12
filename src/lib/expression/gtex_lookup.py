"""GTEx gene × tissue median TPM lookup for B3."""

from __future__ import annotations

import gzip
import math
from functools import lru_cache
from pathlib import Path

import mygene
import pandas as pd

from src.lib.settings import B3CoexpressionConfig
from src.lib.track_b.scoring import minmax
from src.lib.track_b.sources import _querymany_with_retry


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_gtex_path(rel_or_abs: str) -> Path | None:
    """Resolve configured path; also accept any *gene_median_tpm*.gct.gz in the folder."""
    root = _repo_root()
    path = Path(rel_or_abs)
    if not path.is_absolute():
        path = root / path
    if path.is_file():
        return path
    parent = path.parent
    if parent.is_dir():
        matches = sorted(parent.glob("*gene_median_tpm*.gct.gz"))
        if matches:
            return matches[0]
        matches = sorted(parent.glob("*gene_median_tpm*.gct"))
        if matches:
            return matches[0]
    return None


def strip_ensembl_version(gene_id: str) -> str:
    g = str(gene_id).strip()
    if "." in g and g.startswith("ENSG"):
        return g.split(".", 1)[0]
    return g


@lru_cache(maxsize=2)
def load_gtex_median_table(path_str: str) -> pd.DataFrame:
    """
    Load GTEx GCT median TPM.
    Index = Ensembl gene id (no version). Columns = tissue names.
    """
    path = Path(path_str)
    open_fn = gzip.open if str(path).endswith(".gz") else open
    with open_fn(path, "rt", encoding="utf-8") as fh:
        _ = fh.readline()
        _ = fh.readline()
        df = pd.read_csv(fh, sep="\t")
    if "Name" not in df.columns:
        raise ValueError(f"GTEx GCT missing Name column: {path}")
    df["ensembl_gene_id"] = df["Name"].map(strip_ensembl_version)
    tissue_cols = [c for c in df.columns if c not in ("Name", "Description", "ensembl_gene_id")]
    slim = df[["ensembl_gene_id", *tissue_cols]].drop_duplicates(
        subset=["ensembl_gene_id"], keep="first"
    )
    return slim.set_index("ensembl_gene_id")


def _norm_tissue_token(s: str) -> str:
    """Normalize spaces/hyphens/parens so 'Brain - Cortex' ~= 'Brain_Cortex'."""
    out = s.strip().lower()
    for ch in (" ", "-", "(", ")", "/"):
        out = out.replace(ch, "_")
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def map_tissue_column(
    tissue: str | None, cfg: B3CoexpressionConfig, columns: list[str]
) -> str | None:
    """Map user tissue string to a GTEx column name."""
    key = (tissue or cfg.default_tissue or "").strip().lower()
    if not key:
        key = (cfg.default_tissue or "brain").strip().lower()

    mapped = cfg.tissue_map.get(key)
    if mapped and mapped in columns:
        return mapped

    lower_map = {c.lower(): c for c in columns}
    norm_map = {_norm_tissue_token(c): c for c in columns}

    if key in lower_map:
        return lower_map[key]
    if _norm_tissue_token(key) in norm_map:
        return norm_map[_norm_tissue_token(key)]
    if mapped:
        if mapped.lower() in lower_map:
            return lower_map[mapped.lower()]
        if _norm_tissue_token(mapped) in norm_map:
            return norm_map[_norm_tissue_token(mapped)]

    # Prefer Cortex over other Brain_* when user said "brain"
    if key == "brain":
        for preferred in ("Brain_Cortex", "Brain_Frontal_Cortex_BA9"):
            if preferred in columns:
                return preferred

    hits = [c for c in columns if key and key in c.lower()]
    if hits:
        # Prefer shorter / more general match when several contain the key
        hits.sort(key=lambda c: (0 if c.lower().endswith(key) else 1, len(c)))
        return hits[0]
    if mapped:
        token = _norm_tissue_token(mapped.split("-")[0].split("_")[0])
        for c in columns:
            if token and token in c.lower():
                return c
    return None


def symbols_to_ensembl(symbols: list[str]) -> dict[str, str]:
    """Map gene symbols → Ensembl gene ids via mygene."""
    out: dict[str, str] = {}
    if not symbols:
        return out
    mg = mygene.MyGeneInfo()
    uniq = sorted({s.upper().strip() for s in symbols if s and str(s).strip()})
    for i in range(0, len(uniq), 200):
        batch = uniq[i : i + 200]
        res = _querymany_with_retry(
            mg,
            batch,
            scopes="symbol",
            fields="symbol,ensembl.gene",
            species="human",
            as_dataframe=False,
            verbose=False,
        )
        for row in res:
            if row.get("notfound"):
                continue
            q = str((row.get("query") or row.get("symbol") or "")).upper().strip()
            if not q:
                continue
            ens = _extract_ensembl(row.get("ensembl"))
            if ens:
                out[q] = strip_ensembl_version(ens)
    return out


def _extract_ensembl(ens: object) -> str | None:
    if ens is None:
        return None
    if isinstance(ens, str):
        return ens
    if isinstance(ens, dict):
        g = ens.get("gene")
        return str(g) if g else None
    if isinstance(ens, list):
        for item in ens:
            got = _extract_ensembl(item)
            if got:
                return got
    return None


def score_gtex_tissue(
    b1: pd.DataFrame,
    *,
    tissue: str | None,
    cfg: B3CoexpressionConfig,
) -> pd.DataFrame | None:
    """
    Score candidates by GTEx median TPM in the mapped tissue.
    Returns None if GTEx file or tissue column cannot be used.
    """
    path = resolve_gtex_path(cfg.gtex_median_path)
    if path is None:
        return None

    table = load_gtex_median_table(str(path))
    tissue_col = map_tissue_column(tissue, cfg, list(table.columns))
    if tissue_col is None:
        print(f"B3 GTEx: no tissue column for '{tissue}'; falling back if hybrid/string.")
        return None

    symbols = b1["candidate_gene_symbol"].fillna("").astype(str).str.upper().str.strip()
    ens_map = symbols_to_ensembl(symbols.tolist())

    tpms: list[float | None] = []
    ensembl_ids: list[str | None] = []
    for sym in symbols:
        ens = ens_map.get(sym) if sym else None
        ensembl_ids.append(ens)
        if not ens or ens not in table.index:
            tpms.append(None)
            continue
        try:
            tpms.append(float(table.at[ens, tissue_col]))
        except (TypeError, ValueError):
            tpms.append(None)

    present_idx = [i for i, v in enumerate(tpms) if v is not None]
    present_log = [math.log1p(max(0.0, float(tpms[i]))) for i in present_idx]
    present_norm = minmax(present_log)
    norm_by_i = dict(zip(present_idx, present_norm, strict=False))

    out = pd.DataFrame(
        {
            "candidate_gene_symbol": b1["candidate_gene_symbol"].astype(str).values,
            "ensembl_gene_id": ensembl_ids,
            "gtex_tissue": tissue_col,
            "tissue_tpm": tpms,
            "gtex_expression_score": [norm_by_i.get(i) for i in range(len(tpms))],
        }
    )
    out["b3_method"] = [
        "gtex_tissue" if i in norm_by_i else "gtex_missing" for i in range(len(tpms))
    ]
    print(
        f"B3 GTEx: tissue={tissue_col!r} file={path.name} "
        f"hits={len(present_idx)}/{len(tpms)}"
    )
    return out
