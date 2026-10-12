"""Run discovery, status, and result previews (registry-backed)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.lib.paths import run_dir
from src.lib.registry.models import run_to_dict
from src.lib.registry.repository import get_run, list_artifacts, list_runs_for_user, user_can_access_run
from src.lib.registry.storage_layout import read_run_meta
from src.lib.run_manifest import read_manifest
from web.catalog import ARTIFACT_CHECKS, PIPELINE_LAYERS


def list_runs(*, user_id: str | None = None) -> list[dict[str, Any]]:
    records = list_runs_for_user(user_id, include_legacy=True, include_archived=False)
    runs: list[dict[str, Any]] = []
    for r in records:
        entry = run_to_dict(r)
        if not entry.get("created_at"):
            mp = run_dir(r.run_id) / "manifest.json"
            if mp.is_file():
                try:
                    m = read_manifest(mp)
                    entry["created_at"] = m.created_at
                    entry["disease"] = entry.get("disease") or m.input.disease_label
                    entry["subtype"] = entry.get("subtype") or m.input.disease_subtype
                    entry["tissue"] = entry.get("tissue") or m.input.tissue
                    entry["ontology_id"] = entry.get("ontology_id") or m.disease_resolution.selected.id
                    entry["ontology_name"] = entry.get("ontology_name") or m.disease_resolution.selected.name
                except Exception:
                    pass
        runs.append(entry)
    return runs


def assert_run_access(user_id: str | None, run_id: str) -> None:
    if not user_can_access_run(user_id, run_id):
        from fastapi import HTTPException

        raise HTTPException(404, "Run not found")


def _step2_literature_note(base: Path) -> str | None:
    summary_path = base / "artifacts" / "step2_summary.json"
    if not summary_path.is_file():
        return None
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("literature_skipped"):
        return "Open Targets only (RAG skipped)"
    if not data.get("literature_enabled"):
        return "Literature RAG disabled in config"
    lit = data.get("literature_rag") or {}
    return (
        f"RAG: {lit.get('article_count', 0)} articles, "
        f"{lit.get('literature_row_count', 0)} literature genes"
    )


def _step_b3_note(base: Path) -> str | None:
    """Human label: GTEx vs STRING proxy for Track B step B3."""
    summary_path = base / "artifacts" / "track_b" / "stepB3_summary.json"
    if summary_path.is_file():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            label = data.get("label")
            if label:
                return str(label)
            if data.get("used_gtex"):
                tissue = data.get("gtex_tissue") or "?"
                return f"B3: GTEx ({tissue})"
            return "B3: STRING proxy only (no GTEx)"
        except Exception:
            pass
    # Fallback: inspect CSV b3_method column from older runs
    csv_path = base / "artifacts" / "track_b" / "stepB3_coexpression.csv"
    if not csv_path.is_file():
        return None
    try:
        import pandas as pd

        df = pd.read_csv(csv_path, usecols=lambda c: c in ("b3_method", "gtex_tissue"))
        if "b3_method" not in df.columns:
            return "B3: legacy (no method column)"
        counts = df["b3_method"].astype(str).value_counts().to_dict()
        gtexish = int(counts.get("hybrid", 0)) + int(counts.get("gtex_tissue", 0))
        if gtexish > 0:
            tissue = None
            if "gtex_tissue" in df.columns:
                nn = df["gtex_tissue"].dropna()
                if len(nn):
                    tissue = str(nn.iloc[0])
            return f"B3: GTEx ({tissue or 'ok'}) — {gtexish}/{len(df)} genes"
        return "B3: STRING proxy only (no GTEx)"
    except Exception:
        return None


def run_status(run_id: str) -> dict[str, Any]:
    base = run_dir(run_id)
    if not base.is_dir():
        return {"run_id": run_id, "exists": False, "artifacts": {}, "steps": []}

    artifacts_db = [
        {
            "type": a.artifact_type,
            "path": a.file_path,
            "row_count": a.row_count,
            "checksum_sha256": a.checksum_sha256,
        }
        for a in list_artifacts(run_id)
    ]

    artifacts: dict[str, bool] = {}
    for key, rel in ARTIFACT_CHECKS.items():
        artifacts[key] = (base / rel).is_file()

    step_status: list[dict[str, Any]] = []
    for layer in PIPELINE_LAYERS:
        for step in layer["steps"]:
            resolved: list[Path] = []
            for o in step["outputs"]:
                if o in ("manifest.json", "inputs.json"):
                    resolved.append(base / o)
                else:
                    resolved.append(base / "artifacts" / o)
            done = all(p.is_file() for p in resolved)
            entry: dict[str, Any] = {
                "id": step["id"],
                "name": step["name"],
                "layer": layer["id"],
                "done": done,
                "outputs": [str(p.relative_to(base)) for p in resolved if p.is_file()],
            }
            if step["id"] == "step2" and done:
                note = _step2_literature_note(base)
                if note:
                    entry["literature"] = note
            if step["id"] == "stepB3" and done:
                b3_note = _step_b3_note(base)
                if b3_note:
                    entry["b3_note"] = b3_note
            step_status.append(entry)

    manifest_data: dict[str, Any] | None = None
    mp = base / "manifest.json"
    if mp.is_file():
        manifest_data = json.loads(mp.read_text(encoding="utf-8"))

    run_meta = read_run_meta(base)
    reg = get_run(run_id)

    return {
        "run_id": run_id,
        "exists": True,
        "artifacts": artifacts,
        "artifacts_index": artifacts_db,
        "steps": step_status,
        "manifest": manifest_data,
        "run_meta": run_meta,
        "registry": run_to_dict(reg) if reg else None,
    }


def preview_csv(run_id: str, artifact: str, limit: int = 25) -> dict[str, Any]:
    mapping = {
        "known_genes": "artifacts/known_disease_genes.csv",
        "track_a": "artifacts/track_a/ranked_known_targets.csv",
        "track_b": "artifacts/track_b/ranked_novel_candidates.csv",
        "fusion": "artifacts/fusion/unified_target_portfolio.csv",
        "track_a_a1": "artifacts/track_a/stepA1_saturation.csv",
        "track_b_b1": "artifacts/track_b/stepB1_candidate_neighbors.csv",
    }
    rel = mapping.get(artifact)
    if not rel:
        raise ValueError(f"Unknown artifact: {artifact}")
    path = run_dir(run_id) / rel
    if not path.is_file():
        raise FileNotFoundError(f"Missing: {path}")
    df = pd.read_csv(path).head(limit)
    return {
        "artifact": artifact,
        "path": str(path),
        "rows_total": len(pd.read_csv(path)),
        "columns": list(df.columns),
        "rows": df.fillna("").astype(str).to_dict(orient="records"),
    }
