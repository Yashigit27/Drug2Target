from __future__ import annotations

from pathlib import Path

from src.lib.settings import load_config


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def outputs_dir() -> Path:
    root = repo_root()
    return root / load_config().paths.outputs_dir


def run_dir(run_id: str) -> Path:
    from src.lib.registry.paths_resolver import resolve_run_dir

    return resolve_run_dir(run_id)


def ensure_run_dir(run_id: str) -> Path:
    d = run_dir(run_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "artifacts").mkdir(exist_ok=True)
    (d / "logs").mkdir(exist_ok=True)
    (d / "provenance").mkdir(exist_ok=True)
    return d


def manifest_path(run_id: str) -> Path:
    return run_dir(run_id) / "manifest.json"


def inputs_path(run_id: str) -> Path:
    return run_dir(run_id) / "inputs.json"


def data_raw_dir() -> Path:
    cfg = load_config()
    legacy_root = repo_root() / cfg.paths.data_raw_dir
    legacy_root.mkdir(parents=True, exist_ok=True)
    return legacy_root


def raw_dir(run_id: str) -> Path:
    """Per-run raw API cache directory (prefers storage/raw/<run_id>)."""
    from src.lib.registry.storage_layout import raw_dir_for_run

    return raw_dir_for_run(run_id)
