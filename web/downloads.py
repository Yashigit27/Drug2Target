"""Zip artifact bundles for download."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

from src.lib.paths import run_dir

_INCLUDE_PREFIXES = (
    "manifest.json",
    "inputs.json",
    "run_meta.json",
    "artifacts/",
    "logs/",
    "provenance/",
    "snakemake_runtime.yaml",
)


def build_run_zip(run_id: str) -> bytes:
    base = run_dir(run_id)
    if not base.is_dir():
        raise FileNotFoundError(f"Run not found: {run_id}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(base).as_posix()
            if not any(rel == p or rel.startswith(p) for p in _INCLUDE_PREFIXES):
                continue
            zf.write(path, arcname=f"{run_id}/{rel}")
    return buf.getvalue()
