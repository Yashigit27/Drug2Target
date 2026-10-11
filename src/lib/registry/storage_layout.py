"""Structured storage layout: users/runs, provenance, run_meta, logs."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from src import __version__
from src.lib.settings import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def storage_root() -> Path:
    cfg = load_config()
    rel = getattr(cfg.paths, "storage_dir", "storage")
    root = _repo_root() / rel
    root.mkdir(parents=True, exist_ok=True)
    return root


def raw_cache_root() -> Path:
    root = storage_root() / "raw"
    root.mkdir(parents=True, exist_ok=True)
    return root


def user_runs_root(user_id: str) -> Path:
    root = storage_root() / "users" / user_id / "runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def legacy_outputs_rel(run_id: str) -> str:
    cfg = load_config()
    return f"{cfg.paths.outputs_dir}/{run_id}".replace("\\", "/")


def user_run_rel(user_id: str, run_id: str) -> str:
    cfg = load_config()
    base = getattr(cfg.paths, "storage_dir", "storage")
    return f"{base}/users/{user_id}/runs/{run_id}".replace("\\", "/")


def prepare_user_run_layout(user_id: str, run_id: str) -> Path:
    """Create storage/users/<user_id>/runs/<run_id>/ with subdirs."""
    base = user_runs_root(user_id) / run_id
    for sub in ("artifacts", "logs", "provenance"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def prepare_legacy_run_layout(run_id: str) -> Path:
    from src.lib.paths import outputs_dir

    base = outputs_dir() / run_id
    for sub in ("artifacts", "logs", "provenance"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def raw_dir_for_run(run_id: str) -> Path:
    """Prefer storage/raw/<run_id>, fall back to legacy data/raw."""
    new_path = raw_cache_root() / run_id
    new_path.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    legacy = _repo_root() / cfg.paths.data_raw_dir / run_id
    if legacy.is_dir() and not any(new_path.iterdir()):
        return legacy
    return new_path


def run_meta_path(run_base: Path) -> Path:
    return run_base / "run_meta.json"


def write_run_meta(run_base: Path, meta: dict[str, Any]) -> None:
    path = run_meta_path(run_base)
    path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def read_run_meta(run_base: Path) -> dict[str, Any] | None:
    path = run_meta_path(run_base)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_run_meta(run_base: Path, **updates: Any) -> dict[str, Any]:
    meta = read_run_meta(run_base) or {}
    meta.update(updates)
    write_run_meta(run_base, meta)
    return meta


def write_provenance_snapshot(run_base: Path) -> None:
    prov = run_base / "provenance"
    prov.mkdir(parents=True, exist_ok=True)

    cfg_src = _repo_root() / "config" / "default.yaml"
    if cfg_src.is_file():
        shutil.copy2(cfg_src, prov / "config_snapshot.yaml")

    (prov / "pipeline_version.txt").write_text(
        f"{__version__}\n", encoding="utf-8"
    )

    commit = _git_commit_hash()
    if commit:
        (prov / "git_commit.txt").write_text(commit + "\n", encoding="utf-8")

    timings_path = prov / "step_timings.json"
    if not timings_path.is_file():
        timings_path.write_text("[]", encoding="utf-8")


def append_step_timing(run_base: Path, step: str, *, started_at: str, finished_at: str) -> None:
    prov = run_base / "provenance" / "step_timings.json"
    entries: list[dict[str, Any]] = []
    if prov.is_file():
        try:
            entries = json.loads(prov.read_text(encoding="utf-8"))
        except Exception:
            entries = []
    entries.append({"step": step, "started_at": started_at, "finished_at": finished_at})
    prov.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _git_commit_hash() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(_repo_root()),
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


class RunLogWriter:
    """Append pipeline log lines to logs/pipeline.log."""

    def __init__(self, run_base: Path) -> None:
        self.log_dir = run_base / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / "pipeline.log"

    def write(self, msg: str) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self.path.open("a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_initial_run_meta(
    *,
    run_id: str,
    user_id: str | None,
    job_id: str,
    command: str,
    approach: str | None,
    use_snakemake: bool,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "user_id": user_id,
        "job_id": job_id,
        "status": "queued",
        "command": command,
        "approach": approach,
        "use_snakemake": use_snakemake,
        "params": {
            "disease": params.get("disease"),
            "subtype": params.get("subtype"),
            "tissue": params.get("tissue"),
            "disease_id": params.get("disease_id"),
            "skip_literature": params.get("skip_literature"),
        },
        "started_at": None,
        "finished_at": None,
        "error": None,
        "pipeline_version": __version__,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
