"""Choose a disease-versus-healthy study when B4 has none saved yet.

Expression Atlas is searched once. The winning table is saved and reused.
A file that is not a gene / fold-change / p-value table is skipped.
"""

from __future__ import annotations

import gzip
import io
import re
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import httpx

from src.lib.expression.de_contrast import (
    contrast_pairs,
    count_changed,
    load_contrast,
    read_expression_table,
    resolve_table_path,
    save_pinned,
    tissue_key,
)
from src.lib.http_client import make_http_client
from src.lib.paths import repo_root
from src.lib.settings import B4ContrastConfig, B4ExpressionConfig

ATLAS_EXPERIMENTS = "https://www.ebi.ac.uk/gxa/json/experiments"
ATLAS_FTP = "https://ftp.ebi.ac.uk/pub/databases/microarray/data/atlas/experiments"
MIN_CHANGED = 50
MAX_EXPERIMENTS = 6
MAX_BYTES = 25_000_000
_STOP = {
    "disease",
    "disorder",
    "syndrome",
    "human",
    "type",
    "late",
    "onset",
    "early",
    "the",
    "and",
    "with",
    "of",
    "stage",
    "cancer",
    "carcinoma",
    "tumor",
    "tumour",
    "mellitus",
}
_HEALTHY = ("normal", "healthy", "control", "none", "unaffected", "ctrl")
_MODEL = ("organoid", "in vitro", "cell line", "ipsc", "cultured")
_SKIP_NAME = (
    "undecorated",
    "percentile",
    "gsea",
    "sdrf",
    "configuration",
    "bedgraph",
    ".xml",
    ".png",
    ".pdf",
    ".rdata",
    ".eps",
    ".idf",
    ".html",
    ".rda",
)


@dataclass
class _Candidate:
    accession: str
    contrast: str | None
    remote_name: str
    n_samples: int
    tissue_label: str
    description: str
    changed: int = 0
    local_path: Path | None = None

    @property
    def model_system(self) -> bool:
        return any(word in self.description.lower() for word in _MODEL)


def ensure_contrast(
    disease_id: str,
    disease_name: str,
    tissue: str | None,
    cfg: B4ExpressionConfig,
) -> B4ContrastConfig | None:
    """Return a saved contrast, recovering or choosing one when the file is absent."""
    from src.lib.expression.de_contrast import find_contrast

    group = tissue_key(tissue, cfg)
    row = find_contrast(disease_id, tissue, cfg)
    if row is not None and resolve_table_path(row.file).is_file():
        return row
    if row is not None:
        recovered = _recover(row)
        if recovered is not None:
            print(f"B4 found the results table for {row.study} under a different file name")
            return recovered

    print(f"B4 searching Expression Atlas for {disease_name} / {group}")
    try:
        chosen = _search(disease_id, disease_name, group, cfg)
    except Exception as exc:
        print(f"B4 study search could not finish ({exc}); scores left neutral")
        return None
    if chosen is None:
        print(f"B4 no usable contrast for {disease_id} / {group}; scores left neutral")
        return None
    save_pinned(chosen)
    label = chosen.tissue_label or group
    print(
        f"B4 selected {chosen.study} {chosen.contrast or ''} "
        f"({label}, {chosen.pass_count} genes changed, n={chosen.n_samples})"
    )
    return chosen


def _search(
    disease_id: str,
    disease_name: str,
    group: str,
    cfg: B4ExpressionConfig,
) -> B4ContrastConfig | None:
    tokens = _tokens(disease_name)[:1]
    words = [word.lower() for word in cfg.tissue_group.get(group, [group])]
    if not tokens:
        return None
    with make_http_client(follow_redirects=True, timeout=60.0) as client:
        experiments = _matching_experiments(client, tokens, words)
        print(f"B4 found {len(experiments)} human differential studies")
        if not experiments:
            return None
        found: list[_Candidate] = []
        for experiment in experiments[:MAX_EXPERIMENTS]:
            found.extend(_candidates_in_experiment(client, experiment, tokens, words))
        ranked = _rank(client, found, cfg)
    if not ranked:
        return None
    best = ranked[0]
    if best.local_path is None:
        return None
    relative = best.local_path
    try:
        relative = best.local_path.relative_to(repo_root())
    except ValueError:
        pass
    return B4ContrastConfig(
        disease_id=disease_id,
        tissue=group,
        study=best.accession,
        file=str(relative).replace("\\", "/"),
        contrast=best.contrast,
        pass_count=best.changed,
        n_samples=best.n_samples,
        tissue_label=best.tissue_label,
    )


def _matching_experiments(client: httpx.Client, tokens: list[str], words: list[str]) -> list[dict]:
    response = client.get(ATLAS_EXPERIMENTS)
    response.raise_for_status()
    experiments = response.json().get("experiments") or []
    matched = []
    for experiment in experiments:
        if str(experiment.get("species", "")).lower() != "homo sapiens":
            continue
        if str(experiment.get("experimentType", "")).lower() != "differential":
            continue
        text = str(experiment.get("experimentDescription") or "")
        if not all(token in text.lower() for token in tokens):
            continue
        matched.append(experiment)
    matched.sort(key=lambda item: int(item.get("numberOfAssays") or 0), reverse=True)
    # Studies that already name the tissue are inspected first. Others are
    # still opened, because the tissue is often only in the sample labels.
    named = [
        item
        for item in matched
        if any(word in str(item.get("experimentDescription") or "").lower() for word in words)
    ]
    rest = [item for item in matched if item not in named]
    return named + rest


def _candidates_in_experiment(
    client: httpx.Client,
    experiment: dict,
    tokens: list[str],
    words: list[str],
) -> list[_Candidate]:
    accession = str(experiment.get("experimentAccession") or "")
    description = str(experiment.get("experimentDescription") or "")
    if not accession:
        return []
    groups = _assay_groups(client, accession)
    names = _remote_names(client, accession)
    allowed = _allowed_contrasts(groups, tokens, words, description)
    if allowed is not None and not allowed:
        return []
    found: list[_Candidate] = []
    for name in _ordered_names(names):
        pairs = _peek_pairs(client, accession, name)
        pairs = _keep_pairs(pairs, allowed)
        if not pairs:
            continue
        for contrast_id, _fold, _p_col in pairs:
            label, n_samples = _contrast_facts(contrast_id, groups)
            found.append(
                _Candidate(
                    accession=accession,
                    contrast=contrast_id,
                    remote_name=name,
                    n_samples=n_samples,
                    tissue_label=label,
                    description=description,
                )
            )
        if found:
            break
    return found


def _rank(client: httpx.Client, found: list[_Candidate], cfg: B4ExpressionConfig) -> list[_Candidate]:
    ranked: list[_Candidate] = []
    seen: set[tuple[str, str]] = set()
    for candidate in found:
        key = (candidate.accession, candidate.remote_name)
        if key in seen:
            table_path = candidate.local_path
        else:
            seen.add(key)
            table_path = _download(client, candidate)
        if table_path is None:
            continue
        for item in found:
            if (item.accession, item.remote_name) == key:
                item.local_path = table_path
        table = load_contrast(table_path, candidate.contrast)
        if not table:
            continue
        candidate.changed = count_changed(
            table,
            min_abs_log2fc=cfg.min_abs_log2fc,
            max_pvalue=cfg.max_pvalue,
        )
        if candidate.changed < MIN_CHANGED:
            continue
        print(
            f"B4 considered {candidate.accession} {candidate.contrast or ''} "
            f"({candidate.tissue_label or 'tissue not labeled'}, {candidate.changed} genes changed)"
        )
        ranked.append(candidate)
    ranked.sort(
        key=lambda item: (
            item.model_system,
            -item.changed,
            -item.n_samples,
            item.accession,
        )
    )
    return ranked


def _recover(row: B4ContrastConfig) -> B4ContrastConfig | None:
    accession = _accession(row)
    if not accession:
        return None
    dest = resolve_table_path(row.file)
    try:
        with make_http_client(follow_redirects=True, timeout=60.0) as client:
            for name in _ordered_names(_remote_names(client, accession)):
                if not _peek_pairs(client, accession, name):
                    continue
                path = _download_named(client, accession, name, dest)
                if path is None:
                    continue
                if load_contrast(path, row.contrast):
                    return row
    except Exception:
        return None
    return None


def _assay_groups(client: httpx.Client, accession: str) -> dict[str, tuple[str, int]]:
    url = f"{ATLAS_FTP}/{accession}/{accession}-configuration.xml"
    try:
        response = client.get(url)
        if response.status_code != 200 or not response.content:
            return {}
        root = ElementTree.fromstring(response.content)
    except (httpx.HTTPError, ElementTree.ParseError):
        return {}
    groups: dict[str, tuple[str, int]] = {}
    for node in root.iter("assay_group"):
        group_id = node.attrib.get("id") or ""
        label = node.attrib.get("label") or ""
        if group_id:
            groups[group_id] = (label, sum(1 for _ in node.iter("assay")))
    return groups


def _allowed_contrasts(
    groups: dict[str, tuple[str, int]],
    tokens: list[str],
    words: list[str],
    description: str,
) -> set[str | None] | None:
    """Contrast ids that are disease versus healthy in this tissue.

    None means the experiment has no group labels, so every contrast in a
    readable table may be considered.
    """
    if not groups:
        return None
    allowed: set[str | None] = set()
    # Contrast ids are not always listed; the column prefix is gA_gB.
    ids = set(groups)
    for left in ids:
        for right in ids:
            if left == right:
                continue
            contrast_id = f"{left}_{right}"
            label_left, _n_left = groups[left]
            label_right, _n_right = groups[right]
            if _disease_versus_healthy(label_left, label_right, tokens, words, description):
                allowed.add(contrast_id)
    return allowed


def _disease_versus_healthy(
    label_left: str,
    label_right: str,
    tokens: list[str],
    words: list[str],
    description: str,
) -> bool:
    left = label_left.lower()
    right = label_right.lower()
    healthy_left = any(word in left for word in _HEALTHY)
    healthy_right = any(word in right for word in _HEALTHY)
    if healthy_left == healthy_right:
        return False
    disease_text = right if healthy_left else left
    if tokens and not any(token in disease_text for token in tokens):
        return False
    blob = f"{label_left} {label_right} {description}".lower()
    return any(word in blob for word in words) if words else True


def _contrast_facts(contrast_id: str | None, groups: dict[str, tuple[str, int]]) -> tuple[str, int]:
    if not contrast_id or "_" not in contrast_id:
        return "", 0
    match = re.match(r"^(g\d+)_(g\d+)$", contrast_id)
    if not match:
        return "", 0
    left = groups.get(match.group(1))
    right = groups.get(match.group(2))
    labels = [item[0] for item in (left, right) if item]
    counts = [item[1] for item in (left, right) if item and item[1] > 0]
    n_samples = min(counts) if counts else 0
    return "; ".join(labels), n_samples


def _remote_names(client: httpx.Client, accession: str) -> list[str]:
    try:
        response = client.get(f"{ATLAS_FTP}/{accession}/")
        if response.status_code != 200:
            return []
    except httpx.HTTPError:
        return []
    names = []
    for href in re.findall(r'href="([^"]+)"', response.text):
        name = href.split("/")[-1].split("?")[0]
        if not name or name.endswith("/"):
            continue
        names.append(name)
    return names


def _ordered_names(names: list[str]) -> list[str]:
    useful = []
    for name in names:
        low = name.lower()
        if any(piece in low for piece in _SKIP_NAME):
            continue
        useful.append(name)

    def rank(name: str) -> tuple[int, str]:
        low = name.lower()
        if "analytics" in low and low.endswith(".tsv"):
            return (0, name)
        if "analytics" in low:
            return (1, name)
        if low.endswith((".tsv", ".csv", ".txt", ".tab", ".tsv.gz", ".csv.gz", ".txt.gz")):
            return (2, name)
        return (3, name)

    useful.sort(key=rank)
    return [name for name in useful if rank(name)[0] < 3] or useful[:8]


def _keep_pairs(pairs: list, allowed: set[str | None] | None) -> list:
    if not pairs:
        return []
    if allowed is None:
        return pairs[:1] if len(pairs) == 1 else []
    named = [pair for pair in pairs if pair[0] in allowed]
    if named:
        return named
    if len(pairs) == 1 and len(allowed) == 1:
        only = next(iter(allowed))
        contrast_id, fold_col, p_col = pairs[0]
        return [(contrast_id or only, fold_col, p_col)]
    return []


def _peek_pairs(client: httpx.Client, accession: str, name: str) -> list:
    """Read only the header. A missing or unusual file returns no contrasts."""
    url = f"{ATLAS_FTP}/{accession}/{name}"
    try:
        response = client.get(url, headers={"Range": "bytes=0-16383"})
    except httpx.HTTPError:
        return []
    if response.status_code not in {200, 206} or not response.content:
        return []
    raw = response.content
    if name.lower().endswith(".gz"):
        try:
            text = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(8000).decode("utf-8", "replace")
        except (OSError, EOFError, gzip.BadGzipFile):
            return []
    else:
        text = raw.decode("utf-8", "replace")
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.lower().startswith("track"):
            continue
        if "\t" in stripped:
            columns = stripped.split("\t")
        elif "," in stripped:
            columns = [part.strip().strip('"') for part in stripped.split(",")]
        else:
            continue
        pairs = contrast_pairs(columns)
        if pairs:
            return pairs
    return []


def _download(client: httpx.Client, candidate: _Candidate) -> Path | None:
    dest_dir = repo_root() / "data" / "external" / "de"
    suffix = "".join(Path(candidate.remote_name).suffixes) or ".tsv"
    dest = dest_dir / f"{candidate.accession}{suffix}"
    return _download_named(client, candidate.accession, candidate.remote_name, dest)


def _download_named(client: httpx.Client, accession: str, name: str, dest: Path) -> Path | None:
    if dest.is_file() and dest.stat().st_size > 0 and read_expression_table(dest) is not None:
        return dest
    url = f"{ATLAS_FTP}/{accession}/{name}"
    try:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                return None
            length = int(response.headers.get("content-length") or 0)
            if length > MAX_BYTES:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            size = 0
            with tmp.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        handle.close()
                        tmp.unlink(missing_ok=True)
                        return None
                    handle.write(chunk)
            tmp.replace(dest)
    except (httpx.HTTPError, OSError):
        return None
    frame = read_expression_table(dest)
    if frame is None or not contrast_pairs(list(frame.columns)):
        return None
    return dest


def _tokens(disease_name: str) -> list[str]:
    text = disease_name.lower().replace("'", "").replace("’", "")
    parts = re.findall(r"[a-z0-9]+", text)
    tokens = [part for part in parts if part not in _STOP and len(part) >= 4]
    if not tokens:
        tokens = [part for part in parts if part not in _STOP and len(part) >= 3]
    tokens.sort(key=len, reverse=True)
    return tokens


def _accession(row: B4ContrastConfig) -> str | None:
    for value in (Path(row.file).name, row.study):
        match = re.search(r"(E-[A-Z]+-\d+)", str(value), flags=re.I)
        if match:
            return match.group(1).upper()
    return None
