"""CRUD operations for the D2T registry."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from src.lib.registry.db import db_session
from src.lib.registry.models import ArtifactRecord, JobRecord, RunRecord, UserRecord


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_user(row) -> UserRecord:
    return UserRecord(
        user_id=row["user_id"],
        email=row["email"],
        name=row["name"],
        password_hash=row["password_hash"],
        created_at=row["created_at"],
        is_active=bool(row["is_active"]),
    )


def _row_run(row) -> RunRecord:
    return RunRecord(
        run_id=row["run_id"],
        user_id=row["user_id"],
        disease=row["disease"],
        subtype=row["subtype"],
        tissue=row["tissue"],
        ontology_id=row["ontology_id"],
        ontology_name=row["ontology_name"],
        status=row["status"],
        command=row["command"],
        approach=row["approach"],
        use_snakemake=bool(row["use_snakemake"]),
        storage_path=row["storage_path"],
        archived=bool(row["archived"]),
        error=row["error"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


# --- Users ---


def create_user(email: str, password_hash: str, *, name: str | None = None) -> UserRecord:
    user_id = str(uuid.uuid4())
    created_at = _now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, email, name, password_hash, created_at, is_active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (user_id, email.strip().lower(), name, password_hash, created_at),
        )
    return UserRecord(
        user_id=user_id,
        email=email.strip().lower(),
        name=name,
        password_hash=password_hash,
        created_at=created_at,
        is_active=True,
    )


def get_user_by_email(email: str) -> UserRecord | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND is_active = 1",
            (email.strip().lower(),),
        ).fetchone()
    return _row_user(row) if row else None


def get_user_by_id(user_id: str) -> UserRecord | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()
    return _row_user(row) if row else None


# --- Sessions ---


def create_session(user_id: str, *, ttl_hours: int = 168) -> str:
    from datetime import timedelta

    token = uuid.uuid4().hex + uuid.uuid4().hex
    created = datetime.now(timezone.utc)
    expires = created + timedelta(hours=ttl_hours)
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, created.isoformat(), expires.isoformat()),
        )
    return token


def get_user_id_for_session(token: str) -> str | None:
    now = _now()
    with db_session() as conn:
        row = conn.execute(
            """
            SELECT user_id FROM sessions
            WHERE token = ? AND expires_at > ?
            """,
            (token, now),
        ).fetchone()
    return row["user_id"] if row else None


def delete_session(token: str) -> None:
    with db_session() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


# --- Runs ---


def create_run(
    run_id: str,
    storage_path: str,
    *,
    user_id: str | None = None,
    disease: str | None = None,
    subtype: str | None = None,
    tissue: str | None = None,
    command: str | None = None,
    approach: str | None = None,
    use_snakemake: bool = False,
    created_at: str | None = None,
) -> RunRecord:
    created_at = created_at or _now()
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, user_id, disease, subtype, tissue,
                ontology_id, ontology_name, status, command, approach,
                use_snakemake, storage_path, archived, error,
                created_at, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 'queued', ?, ?, ?, ?, 0, NULL, ?, NULL, NULL)
            """,
            (
                run_id,
                user_id,
                disease,
                subtype,
                tissue,
                command,
                approach,
                int(use_snakemake),
                storage_path,
                created_at,
            ),
        )
    return RunRecord(
        run_id=run_id,
        user_id=user_id,
        disease=disease,
        subtype=subtype,
        tissue=tissue,
        ontology_id=None,
        ontology_name=None,
        status="queued",
        command=command,
        approach=approach,
        use_snakemake=use_snakemake,
        storage_path=storage_path,
        archived=False,
        error=None,
        created_at=created_at,
        started_at=None,
        finished_at=None,
    )


def get_run(run_id: str) -> RunRecord | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    return _row_run(row) if row else None


def get_run_storage_path(run_id: str) -> str | None:
    with db_session() as conn:
        row = conn.execute(
            "SELECT storage_path FROM runs WHERE run_id = ? AND archived = 0",
            (run_id,),
        ).fetchone()
    return row["storage_path"] if row else None


def update_run(
    run_id: str,
    *,
    status: str | None = None,
    disease: str | None = None,
    ontology_id: str | None = None,
    ontology_name: str | None = None,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    archived: bool | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    mapping = {
        "status": status,
        "disease": disease,
        "ontology_id": ontology_id,
        "ontology_name": ontology_name,
        "error": error,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    for key, val in mapping.items():
        if val is not None:
            fields.append(f"{key} = ?")
            values.append(val)
    if archived is not None:
        fields.append("archived = ?")
        values.append(int(archived))
    if not fields:
        return
    values.append(run_id)
    with db_session() as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id = ?", values)


def list_runs_for_user(
    user_id: str | None,
    *,
    include_legacy: bool = True,
    include_archived: bool = False,
) -> list[RunRecord]:
    clauses = []
    params: list[Any] = []
    if user_id:
        if include_legacy:
            clauses.append("(user_id = ? OR user_id IS NULL)")
            params.append(user_id)
        else:
            clauses.append("user_id = ?")
            params.append(user_id)
    if not include_archived:
        clauses.append("archived = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_session() as conn:
        rows = conn.execute(
            f"SELECT * FROM runs {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [_row_run(r) for r in rows]


def archive_run(run_id: str) -> None:
    update_run(run_id, archived=True, status="archived")


# --- Jobs ---


def create_job_record(
    job_id: str,
    run_id: str,
    command: str,
    *,
    user_id: str | None = None,
) -> None:
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO jobs (job_id, run_id, user_id, command, status, error, log_summary,
                              started_at, finished_at, duration_sec)
            VALUES (?, ?, ?, ?, 'queued', NULL, NULL, NULL, NULL, NULL)
            """,
            (job_id, run_id, user_id, command),
        )


def update_job_record(
    job_id: str,
    *,
    status: str | None = None,
    error: str | None = None,
    log_summary: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    duration_sec: float | None = None,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    for key, val in {
        "status": status,
        "error": error,
        "log_summary": log_summary,
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_sec": duration_sec,
    }.items():
        if val is not None:
            fields.append(f"{key} = ?")
            values.append(val)
    if not fields:
        return
    values.append(job_id)
    with db_session() as conn:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE job_id = ?", values)


def get_job_record(job_id: str) -> JobRecord | None:
    with db_session() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    if not row:
        return None
    return JobRecord(
        job_id=row["job_id"],
        run_id=row["run_id"],
        user_id=row["user_id"],
        command=row["command"],
        status=row["status"],
        error=row["error"],
        log_summary=row["log_summary"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_sec=row["duration_sec"],
    )


def list_jobs_for_user(user_id: str | None, *, limit: int = 50) -> list[JobRecord]:
    if user_id:
        sql = """
            SELECT * FROM jobs WHERE user_id = ? OR user_id IS NULL
            ORDER BY COALESCE(started_at, finished_at) DESC LIMIT ?
        """
        params: tuple[Any, ...] = (user_id, limit)
    else:
        sql = "SELECT * FROM jobs ORDER BY COALESCE(started_at, finished_at) DESC LIMIT ?"
        params = (limit,)
    with db_session() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        JobRecord(
            job_id=r["job_id"],
            run_id=r["run_id"],
            user_id=r["user_id"],
            command=r["command"],
            status=r["status"],
            error=r["error"],
            log_summary=r["log_summary"],
            started_at=r["started_at"],
            finished_at=r["finished_at"],
            duration_sec=r["duration_sec"],
        )
        for r in rows
    ]


# --- Artifacts ---


def upsert_artifact(record: ArtifactRecord) -> None:
    with db_session() as conn:
        conn.execute(
            "DELETE FROM artifacts WHERE run_id = ? AND artifact_type = ?",
            (record.run_id, record.artifact_type),
        )
        conn.execute(
            """
            INSERT INTO artifacts (run_id, artifact_type, file_path, row_count, checksum_sha256, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                record.run_id,
                record.artifact_type,
                record.file_path,
                record.row_count,
                record.checksum_sha256,
                record.recorded_at,
            ),
        )


def list_artifacts(run_id: str) -> list[ArtifactRecord]:
    with db_session() as conn:
        rows = conn.execute(
            "SELECT * FROM artifacts WHERE run_id = ? ORDER BY artifact_type",
            (run_id,),
        ).fetchall()
    return [
        ArtifactRecord(
            run_id=r["run_id"],
            artifact_type=r["artifact_type"],
            file_path=r["file_path"],
            row_count=r["row_count"],
            checksum_sha256=r["checksum_sha256"],
            recorded_at=r["recorded_at"],
        )
        for r in rows
    ]


def user_can_access_run(user_id: str | None, run_id: str) -> bool:
    run = get_run(run_id)
    if not run or run.archived:
        return False
    if run.user_id is None:
        return True
    if user_id is None:
        return False
    return run.user_id == user_id
