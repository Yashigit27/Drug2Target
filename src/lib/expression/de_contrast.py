"""Saved disease-versus-healthy expression tables for Track B step B4."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd

from src.lib.paths import repo_root
from src.lib.settings import B4ContrastConfig, B4ExpressionConfig

# A results table may name these columns however it likes.
_FOLD_MARKERS = ("log2foldchange", "log2fc", "logfc", "log2fold", "foldchange")
_P_ADJUSTED = ("adjp", "adjustedp", "padj", "fdr", "qvalue")
_P_RAW = ("pvalue", "pval")
_GENE_NAMES = (
    "gene name",
    "gene symbol",
    "gene_symbol",
    "gene symbol",
    "genesymbol",
    "hgnc_symbol",
    "hgnc",
    "symbol",
)


def _norm_id(value: str) -> str:
    return str(value or "").strip().replace(":", "_").upper()


def tissue_key(tissue: str | None, cfg: B4ExpressionConfig) -> str:
    """Map a free-text tissue onto a catalog group such as brain or liver."""
    raw = (tissue or cfg.default_tissue or "brain").strip().lower()
    if raw in cfg.tissue_group:
        return raw
    for group, words in cfg.tissue_group.items():
        for word in words:
            if word and word.lower() in raw:
                return group
    return raw


def pinned_path() -> Path:
    return repo_root() / "data" / "external" / "de" / "pinned.json"


def find_contrast(
    disease_id: str,
    tissue: str | None,
    cfg: B4ExpressionConfig,
) -> B4ContrastConfig | None:
    group = tissue_key(tissue, cfg)
    wanted = _norm_id(disease_id)
    for row in list(cfg.contrasts) + _pinned_rows():
        if _norm_id(row.disease_id) == wanted and row.tissue.strip().lower() == group:
            return row
    return None


def save_pinned(row: B4ContrastConfig) -> None:
    """Remember an automatic choice so the next run does not search again."""
    path = pinned_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.is_file():
        try:
            rows = list(json.loads(path.read_text(encoding="utf-8")).get("contrasts") or [])
        except (OSError, json.JSONDecodeError, TypeError):
            rows = []
    kept = [
        item
        for item in rows
        if not (
            _norm_id(str(item.get("disease_id"))) == _norm_id(row.disease_id)
            and str(item.get("tissue", "")).strip().lower() == row.tissue.strip().lower()
        )
    ]
    kept.append(row.model_dump())
    path.write_text(json.dumps({"contrasts": kept}, indent=2), encoding="utf-8")


def resolve_table_path(rel_or_abs: str) -> Path:
    path = Path(rel_or_abs)
    if not path.is_absolute():
        path = repo_root() / path
    return path


def load_contrast(path: Path, contrast: str | None) -> dict[str, tuple[float, float]]:
    """Return gene symbol -> (log2 fold change, p-value).

    Any table that has a gene column and a fold-change column is accepted.
    A file that is not that kind of table returns an empty map.
    """
    frame = read_expression_table(path)
    if frame is None:
        return {}
    gene_col = _gene_column(frame.columns)
    chosen = _pick_pair(contrast_pairs(list(frame.columns)), contrast)
    if gene_col is None or chosen is None:
        return {}
    _contrast_id, fold_col, p_col = chosen

    best: dict[str, tuple[float, float]] = {}
    for _, row in frame.iterrows():
        symbol = str(row[gene_col] or "").strip().upper()
        if not symbol or symbol in {"NAN", "NONE", "GENE", "GENE NAME"} or symbol.startswith("ENSG"):
            continue
        fold = _as_float(row[fold_col])
        if math.isnan(fold):
            continue
        p_value = _as_float(row[p_col]) if p_col else math.nan
        held = best.get(symbol)
        if held is None or abs(fold) > abs(held[0]):
            best[symbol] = (fold, p_value)
    return best


def count_changed(
    table: dict[str, tuple[float, float]],
    *,
    min_abs_log2fc: float,
    max_pvalue: float,
) -> int:
    return sum(
        score_change(fold, p_value, min_abs_log2fc=min_abs_log2fc, max_pvalue=max_pvalue) > 0
        for fold, p_value in table.values()
    )


def score_change(log2fc: float, p_value: float, *, min_abs_log2fc: float, max_pvalue: float) -> float:
    """0 when the gene was measured but not clearly changed. 1 at a 4-fold change."""
    if math.isnan(log2fc) or math.isnan(p_value):
        return 0.0
    if p_value > max_pvalue or abs(log2fc) < min_abs_log2fc:
        return 0.0
    return min(1.0, abs(log2fc) / 2.0)


def read_expression_table(path: Path) -> pd.DataFrame | None:
    """Read a delimited text table. Return None when the file is not one."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    compression = "gzip" if path.name.lower().endswith(".gz") else None
    for sep in ("\t", ",", ";", None):
        try:
            kwargs: dict = {
                "compression": compression,
                "dtype": str,
                "on_bad_lines": "skip",
                "comment": "#",
            }
            if sep is None:
                frame = pd.read_csv(path, sep=None, engine="python", **kwargs)
            else:
                frame = pd.read_csv(path, sep=sep, **kwargs)
        except (OSError, UnicodeError, ValueError, pd.errors.ParserError):
            continue
        if frame.shape[1] < 2:
            continue
        if _gene_column(frame.columns) and contrast_pairs(list(frame.columns)):
            return frame
    return None


def contrast_pairs(columns) -> list[tuple[str | None, str, str | None]]:
    """Each fold-change column, its contrast id, and a matching p-value column."""
    found: list[tuple[str | None, str, str | None]] = []
    seen: set[str] = set()
    for column in columns:
        if not _is_fold(column):
            continue
        key = str(column)
        if key in seen:
            continue
        seen.add(key)
        prefix = _prefix(key)
        found.append((prefix, key, _match_p(columns, prefix)))
    return found


def _pinned_rows() -> list[B4ContrastConfig]:
    path = pinned_path()
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    rows = []
    for item in payload.get("contrasts") or []:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(B4ContrastConfig.model_validate(item))
        except (TypeError, ValueError):
            continue
    return rows


def _pick_pair(
    pairs: list[tuple[str | None, str, str | None]],
    contrast: str | None,
) -> tuple[str | None, str, str | None] | None:
    if not pairs:
        return None
    if contrast:
        wanted = contrast.strip().lower()
        for pair in pairs:
            if (pair[0] or "").lower() == wanted:
                return pair
        for pair in pairs:
            if wanted and wanted in (pair[0] or "").lower():
                return pair
        return None
    if len(pairs) == 1:
        return pairs[0]
    # Several comparisons and no id: use the one that has a p-value column.
    with_p = [pair for pair in pairs if pair[2]]
    return with_p[0] if len(with_p) == 1 else None


def _gene_column(columns) -> str | None:
    found = _find_column(columns, list(_GENE_NAMES))
    if found is not None:
        return found
    for column in columns:
        low = str(column).strip().lower()
        if "gene" in low and ("name" in low or "symbol" in low):
            return str(column)
    return _find_column(columns, ["gene"])


def _find_column(columns, names: list[str]) -> str | None:
    lookup = {str(column).strip().lower(): column for column in columns}
    for name in names:
        found = lookup.get(name)
        if found is not None:
            return str(found)
    return None


def _is_fold(column) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", str(column).lower())
    return any(marker in compact for marker in _FOLD_MARKERS)


def _prefix(column: str) -> str | None:
    text = column.strip()
    if "." not in text:
        return None
    head, _, tail = text.rpartition(".")
    if _is_fold(tail) or _is_fold(text):
        return head or None
    return None


def _match_p(columns, prefix: str | None) -> str | None:
    ranked: list[tuple[int, str]] = []
    for column in columns:
        text = str(column)
        if prefix and not text.lower().startswith(prefix.lower()):
            continue
        compact = re.sub(r"[^a-z0-9]", "", text.lower())
        if any(marker in compact for marker in _P_ADJUSTED):
            ranked.append((0, text))
        elif any(marker in compact for marker in _P_RAW):
            ranked.append((1, text))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


def _as_float(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    if math.isfinite(number):
        return number
    return math.nan
