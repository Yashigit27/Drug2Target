"""Index run artifacts into the registry database."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from src.lib.registry.models import ArtifactRecord
from src.lib.registry.repository import upsert_artifact
from src.lib.registry.storage_layout import sha256_file

_ARTIFACT_MAP = {
    "manifest.json": "manifest",
    "inputs.json": "inputs",
    "artifacts/known_disease_genes.csv": "known_genes",
    "artifacts/step2_summary.json": "step2_summary",
    "artifacts/track_a/ranked_known_targets.csv": "track_a_final",
    "artifacts/track_b/ranked_novel_candidates.csv": "track_b_final",
    "artifacts/fusion/unified_target_portfolio.csv": "fusion_portfolio",
    "artifacts/fusion/fusion_summary.json": "fusion_summary",
    "artifacts/track_b/stepB1_network_edges.csv": "network_edges",
}


def index_run_artifacts(run_id: str, run_base: Path) -> int:
    """Register known artifacts; returns count indexed."""
    now = datetime.now(timezone.utc).isoformat()
    count = 0
    for rel, artifact_type in _ARTIFACT_MAP.items():
        path = run_base / rel.replace("/", "\\") if "\\" in str(run_base) else run_base / rel
        if not path.is_file():
            continue
        row_count = None
        if path.suffix.lower() == ".csv":
            try:
                row_count = len(pd.read_csv(path))
            except Exception:
                row_count = None
        upsert_artifact(
            ArtifactRecord(
                run_id=run_id,
                artifact_type=artifact_type,
                file_path=rel,
                row_count=row_count,
                checksum_sha256=sha256_file(path),
                recorded_at=now,
            )
        )
        count += 1

    for csv_path in sorted(run_base.rglob("*.csv")):
        rel = csv_path.relative_to(run_base).as_posix()
        if rel in _ARTIFACT_MAP:
            continue
        artifact_type = rel.replace("/", "_").replace(".csv", "")
        upsert_artifact(
            ArtifactRecord(
                run_id=run_id,
                artifact_type=artifact_type,
                file_path=rel,
                row_count=_safe_row_count(csv_path),
                checksum_sha256=sha256_file(csv_path),
                recorded_at=now,
            )
        )
        count += 1
    return count


def _safe_row_count(path: Path) -> int | None:
    try:
        return len(pd.read_csv(path))
    except Exception:
        return None
