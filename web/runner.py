"""Background pipeline execution with registry, logs, and provenance."""

from __future__ import annotations

import json
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable

from src.lib.models import RunInput
from src.lib.paths import run_dir
from src.lib.registry.artifact_index import index_run_artifacts
from src.lib.registry.repository import (
    create_job_record,
    create_run,
    update_job_record,
    update_run,
)
from src.lib.registry.storage_layout import (
    RunLogWriter,
    append_step_timing,
    build_initial_run_meta,
    prepare_user_run_layout,
    update_run_meta,
    user_run_rel,
    write_provenance_snapshot,
    write_run_meta,
)
from src.lib.run_manifest import read_manifest


@dataclass
class Job:
    id: str
    run_id: str
    user_id: str | None
    command: str
    status: str = "queued"
    log: list[str] = field(default_factory=list)
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


_lock = Lock()
_jobs: dict[str, Job] = {}


def _log(job: Job, msg: str, log_writer: RunLogWriter | None = None) -> None:
    job.log.append(msg)
    if log_writer:
        log_writer.write(msg)


def _step2_summary_from_run(run_id: str, skip: bool) -> dict[str, Any]:
    summary_path = run_dir(run_id) / "artifacts" / "step2_summary.json"
    if summary_path.is_file():
        try:
            return json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    csv_path = run_dir(run_id) / "artifacts" / "known_disease_genes.csv"
    merged_rows = 0
    if csv_path.is_file():
        import pandas as pd

        merged_rows = len(pd.read_csv(csv_path))
    return {
        "literature_enabled": False,
        "literature_skipped": skip,
        "merged_rows": merged_rows,
        "literature_rag": None,
    }


def _sync_run_from_manifest(job: Job) -> None:
    mp = run_dir(job.run_id) / "manifest.json"
    if not mp.is_file():
        return
    try:
        m = read_manifest(mp)
        update_run(
            job.run_id,
            disease=m.input.disease_label,
            ontology_id=m.disease_resolution.selected.id,
            ontology_name=m.disease_resolution.selected.name,
        )
    except Exception:
        pass


def _run_step1(job: Job, params: dict[str, Any], log_writer: RunLogWriter | None) -> None:
    from src.step01_input import run_step1

    inp = RunInput(
        disease_label=params["disease"],
        disease_subtype=params.get("subtype"),
        tissue=params.get("tissue"),
        species="human",
    )
    m = run_step1(
        inp,
        disease_id_override=params.get("disease_id"),
        run_id=params.get("run_id") or job.run_id,
    )
    job.run_id = m.run_id
    _log(job, f"Resolved: {m.disease_resolution.selected.id} {m.disease_resolution.selected.name}", log_writer)
    _sync_run_from_manifest(job)


def _run_step2(job: Job, params: dict[str, Any], log_writer: RunLogWriter | None) -> None:
    from src.step02_collect import run_step2

    skip = bool(params.get("skip_literature"))
    if skip:
        _log(job, "Step 2 phase 1/2: Open Targets associations (literature RAG skipped)", log_writer)
    else:
        _log(job, "Step 2 phase 1/2: Open Targets associations", log_writer)
        _log(job, "Step 2 phase 2/2: Europe PMC literature RAG (may take 1-3 minutes)", log_writer)

    raw = run_step2(job.run_id, skip_literature=skip)
    if isinstance(raw, dict):
        result = raw
    elif isinstance(raw, Path):
        result = _step2_summary_from_run(job.run_id, skip)
    else:
        result = _step2_summary_from_run(job.run_id, skip)

    _log(job, f"Wrote known_disease_genes.csv ({result.get('merged_rows', 0)} genes)", log_writer)

    if result.get("literature_enabled"):
        lit = result.get("literature_rag") or {}
        _log(
            job,
            "Literature RAG complete: "
            f"articles={lit.get('article_count', 0)}, "
            f"validated_genes={lit.get('literature_row_count', 0)}, "
            f"literature_only={result.get('literature_only_genes', 0)}",
            log_writer,
        )
    elif skip:
        _log(job, "Literature RAG was disabled for this run (checkbox checked)", log_writer)
    elif not result.get("literature_enabled"):
        _log(job, "Literature RAG disabled in config or environment", log_writer)


_STEP_DISPATCH: dict[str, Callable[[Job], None]] = {
    "stepA1": lambda j: __import__("src.stepA1_saturation", fromlist=["run_step_a1"]).run_step_a1(j.run_id),
    "stepA2": lambda j: __import__("src.stepA2_downweight", fromlist=["run_step_a2"]).run_step_a2(j.run_id),
    "stepA3": lambda j: __import__("src.stepA3_relevance", fromlist=["run_step_a3"]).run_step_a3(j.run_id),
    "stepA4": lambda j: __import__("src.stepA4_cadd_readiness", fromlist=["run_step_a4"]).run_step_a4(j.run_id),
    "stepA5": lambda j: __import__("src.stepA5_rank", fromlist=["run_step_a5"]).run_step_a5(j.run_id),
    "stepB1": lambda j: __import__("src.stepB1_seed_expansion", fromlist=["run_step_b1"]).run_step_b1(j.run_id),
    "stepB2": lambda j: __import__("src.stepB2_functional_similarity", fromlist=["run_step_b2"]).run_step_b2(j.run_id),
    "stepB3": lambda j: __import__("src.stepB3_coexpression", fromlist=["run_step_b3"]).run_step_b3(j.run_id),
    "stepB4": lambda j: __import__("src.stepB4_differential_expression", fromlist=["run_step_b4"]).run_step_b4(j.run_id),
    "stepB5": lambda j: __import__("src.stepB5_pathway", fromlist=["run_step_b5"]).run_step_b5(j.run_id),
    "stepB6": lambda j: __import__("src.stepB6_genetic_support", fromlist=["run_step_b6"]).run_step_b6(j.run_id),
    "stepB7": lambda j: __import__("src.stepB7_network_prioritization", fromlist=["run_step_b7"]).run_step_b7(j.run_id),
    "stepB8": lambda j: __import__("src.stepB8_novelty", fromlist=["run_step_b8"]).run_step_b8(j.run_id),
    "stepB9": lambda j: __import__("src.stepB9_safety_druggability", fromlist=["run_step_b9"]).run_step_b9(j.run_id),
    "stepB10": lambda j: __import__("src.stepB10_rank", fromlist=["run_step_b10"]).run_step_b10(j.run_id),
}


def _execute(
    job: Job,
    steps: list[str],
    params: dict[str, Any],
    log_writer: RunLogWriter,
) -> None:
    job.status = "running"
    job.started_at = datetime.now(timezone.utc).isoformat()
    update_run(job.run_id, status="running", started_at=job.started_at)
    update_job_record(job.id, status="running", started_at=job.started_at)
    update_run_meta(
        run_dir(job.run_id),
        status="running",
        started_at=job.started_at,
        job_id=job.id,
    )
    try:
        for step in steps:
            step_start = datetime.now(timezone.utc).isoformat()
            _log(job, f">> {step}", log_writer)
            if step == "step1":
                _run_step1(job, params, log_writer)
            elif step == "step2":
                _run_step2(job, params, log_writer)
            elif step == "trackA":
                __import__("src.stepA_run_all", fromlist=["run_track_a"]).run_track_a(job.run_id)
                _log(job, "Track A complete", log_writer)
            elif step == "trackB":
                __import__("src.stepB_run_all", fromlist=["run_track_b"]).run_track_b(job.run_id)
                _log(job, "Track B complete", log_writer)
            elif step == "stepF1":
                __import__("src.stepF1_fusion", fromlist=["run_step_f1"]).run_step_f1(job.run_id)
                _log(job, "Fusion F1 complete", log_writer)
            elif step in _STEP_DISPATCH:
                _STEP_DISPATCH[step](job)
                _log(job, f"OK {step} done", log_writer)
            else:
                raise ValueError(f"Unknown step: {step}")
            step_end = datetime.now(timezone.utc).isoformat()
            append_step_timing(run_dir(job.run_id), step, started_at=step_start, finished_at=step_end)
        job.status = "completed"
        update_run(job.run_id, status="completed")
        update_run_meta(run_dir(job.run_id), status="completed", error=None)
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        update_run(job.run_id, status="failed", error=str(exc))
        update_run_meta(run_dir(job.run_id), status="failed", error=str(exc))
        _log(job, traceback.format_exc(), log_writer)
    finally:
        job.finished_at = datetime.now(timezone.utc).isoformat()
        update_run(job.run_id, finished_at=job.finished_at)
        update_run_meta(run_dir(job.run_id), finished_at=job.finished_at)
        duration = _duration_sec(job.started_at, job.finished_at)
        update_job_record(
            job.id,
            status=job.status,
            error=job.error,
            finished_at=job.finished_at,
            log_summary="\n".join(job.log[-30:]),
            duration_sec=duration,
        )
        try:
            index_run_artifacts(job.run_id, run_dir(job.run_id))
        except Exception as exc:
            _log(job, f"Artifact indexing warning: {exc}", log_writer)


def _duration_sec(started: str | None, finished: str | None) -> float | None:
    if not started or not finished:
        return None
    try:
        s = datetime.fromisoformat(started)
        f = datetime.fromisoformat(finished)
        return (f - s).total_seconds()
    except Exception:
        return None


def start_job(
    mode: str,
    params: dict[str, Any],
    custom_step: str | None = None,
    *,
    approach: str | None = None,
    use_snakemake: bool = False,
    user_id: str | None = None,
) -> Job:
    from web.catalog import APPROACH_MODES, RUN_MODES

    if approach:
        if approach not in APPROACH_MODES:
            raise ValueError(f"Unknown approach: {approach}")
        if not params.get("disease"):
            raise ValueError("disease is required")
        steps = list(APPROACH_MODES[approach]["steps"])
        mode = approach
    else:
        mode_def = next((m for m in RUN_MODES if m["id"] == mode), None)
        if not mode_def:
            raise ValueError(f"Unknown mode: {mode}")

        if mode == "custom":
            if not custom_step:
                raise ValueError("custom_step required for custom mode")
            steps = [custom_step]
            if custom_step != "step1" and not params.get("run_id"):
                raise ValueError("run_id required for steps after step1")
        else:
            steps = list(mode_def["steps"])
            if "step1" not in steps and not params.get("run_id"):
                raise ValueError("run_id required")

    run_id = params.get("run_id") or f"web_{uuid.uuid4().hex[:8]}"
    job_id = str(uuid.uuid4())
    command = mode if not approach else f"approach:{approach}"

    if user_id:
        run_base = prepare_user_run_layout(user_id, run_id)
        storage_rel = user_run_rel(user_id, run_id)
    else:
        from src.lib.registry.storage_layout import prepare_legacy_run_layout, legacy_outputs_rel

        run_base = prepare_legacy_run_layout(run_id)
        storage_rel = legacy_outputs_rel(run_id)

    create_run(
        run_id,
        storage_rel,
        user_id=user_id,
        disease=params.get("disease"),
        subtype=params.get("subtype"),
        tissue=params.get("tissue"),
        command=command,
        approach=approach,
        use_snakemake=use_snakemake,
    )
    create_job_record(job_id, run_id, command, user_id=user_id)

    meta = build_initial_run_meta(
        run_id=run_id,
        user_id=user_id,
        job_id=job_id,
        command=command,
        approach=approach,
        use_snakemake=use_snakemake,
        params=params,
    )
    write_run_meta(run_base, meta)
    write_provenance_snapshot(run_base)

    job = Job(id=job_id, run_id=run_id, user_id=user_id, command=command)
    log_writer = RunLogWriter(run_base)

    def _worker() -> None:
        merged = {**params, "run_id": run_id}
        if use_snakemake:
            from web.snakemake_runner import run_snakemake_pipeline

            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
            update_run(job.run_id, status="running", started_at=job.started_at)
            update_job_record(job.id, status="running", started_at=job.started_at)
            update_run_meta(run_base, status="running", started_at=job.started_at)
            try:
                _log(job, ">> snakemake workflow", log_writer)
                run_snakemake_pipeline(
                    run_id,
                    merged,
                    approach=approach or "both",
                    cores=2,
                    log_fn=lambda m: _log(job, m, log_writer),
                )
                job.status = "completed"
                update_run(job.run_id, status="completed")
                _sync_run_from_manifest(job)
                update_run_meta(run_base, status="completed", error=None)
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                update_run(job.run_id, status="failed", error=str(exc))
                update_run_meta(run_base, status="failed", error=str(exc))
                _log(job, traceback.format_exc(), log_writer)
            finally:
                job.finished_at = datetime.now(timezone.utc).isoformat()
                update_run(job.run_id, finished_at=job.finished_at)
                update_run_meta(run_base, finished_at=job.finished_at)
                duration = _duration_sec(job.started_at, job.finished_at)
                update_job_record(
                    job.id,
                    status=job.status,
                    error=job.error,
                    finished_at=job.finished_at,
                    log_summary="\n".join(job.log[-30:]),
                    duration_sec=duration,
                )
                try:
                    index_run_artifacts(job.run_id, run_dir(job.run_id))
                except Exception:
                    pass
        else:
            _execute(job, steps, merged, log_writer)

    Thread(target=_worker, daemon=True).start()

    with _lock:
        _jobs[job.id] = job
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        mem = _jobs.get(job_id)
    if mem:
        return mem
    from src.lib.registry.repository import get_job_record

    rec = get_job_record(job_id)
    if not rec:
        return None
    return Job(
        id=rec.job_id,
        run_id=rec.run_id,
        user_id=rec.user_id,
        command=rec.command,
        status=rec.status,
        log=(rec.log_summary or "").split("\n") if rec.log_summary else [],
        error=rec.error,
        started_at=rec.started_at,
        finished_at=rec.finished_at,
    )


def list_jobs() -> list[Job]:
    with _lock:
        return sorted(_jobs.values(), key=lambda j: j.started_at or "", reverse=True)
