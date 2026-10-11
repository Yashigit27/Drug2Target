"""Run the Snakemake workflow from the web/API layer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

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
    cores: int = 2,
    log_fn=None,
) -> None:
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
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.stdout and log_fn:
        for line in proc.stdout.splitlines():
            log_fn(line)
    if proc.stderr and log_fn:
        for line in proc.stderr.splitlines():
            if line.strip():
                log_fn(line)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout or "Snakemake failed")
