"""Resolve run directories from registry without circular imports."""

from __future__ import annotations

from pathlib import Path

from src.lib.settings import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_run_dir(run_id: str) -> Path:
    """Resolve run directory from registry, legacy outputs, or default path."""
    from src.lib.registry.repository import get_run_storage_path

    rel = get_run_storage_path(run_id)
    root = _repo_root()
    if rel:
        path = root / rel.replace("/", "\\") if "\\" in str(root) else root / rel
        if path.is_dir() or not path.exists():
            return path

    cfg = load_config()
    legacy = root / cfg.paths.outputs_dir / run_id
    if legacy.is_dir():
        return legacy

    if rel:
        return root / rel

    return legacy
