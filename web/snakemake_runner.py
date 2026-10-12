"""Run the Snakemake workflow from the web/API layer."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import yaml

from src.lib.paths import repo_root, run_dir
from src.lib.registry.repository import get_run


def _approach_flags(approach: str) -> dict[str, bool]:
    if approach == "track_a":
        return {"run_track_a": True, "run_track_b": False}
    if approach == "track_b":
        return {"run_track_a": False, "run_track_b": True}
    return {"run_track_a": True, "run_track_b": True}


def write_runtime_config(run_id: str, params: dict[str, Any], *, approach: str = "both") -> Path:
    flags = _approach_flags(approach)
    rec = get_run(run_id)
    output_base = rec.storage_path.replace("\\", "/") if rec else f"outputs/{run_id}"
    cfg = {
        "run_id": run_id,
        "output_base": output_base,
        "disease": params.get("disease") or "",
        "subtype": params.get("subtype"),
        "tissue": params.get("tissue"),
        "disease_id": params.get("disease_id"),
        "skip_literature": bool(params.get("skip_literature")),
        "run_track_a": flags["run_track_a"],
        "run_track_b": flags["run_track_b"],
        "run_fusion": True,
    }
    out = run_dir(run_id)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "snakemake_runtime.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def run_snakemake_pipeline(
    run_id: str,
    params: dict[str, Any],
    *,
    approach: str = "both",
    cores: int = 1,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """
    Run Snakemake and stream logs line-by-line (so the UI does not look stuck).

    Default cores=1: Track A then Track B sequentially — fewer parallel API
    collisions (mygene/Europe PMC) than cores=2.
    """
    cfg_path = write_runtime_config(run_id, params, approach=approach)
    cmd = [
        sys.executable,
        "-m",
        "snakemake",
        "-c",
        str(max(1, cores)),
        "--configfile",
        str(cfg_path),
    ]
    if log_fn:
        log_fn(f"Snakemake: {' '.join(cmd)}")

    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo_root()),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        msg = line.rstrip()
        if msg and log_fn:
            log_fn(msg)
    code = proc.wait()
    if code != 0:
        raise RuntimeError(f"Snakemake failed (exit {code}). See log above.")
