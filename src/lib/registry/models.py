"""Registry datamodels (not SQLAlchemy — plain dataclasses)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class UserRecord:
    user_id: str
    email: str
    name: str | None
    password_hash: str
    created_at: str
    is_active: bool = True


@dataclass
class RunRecord:
    run_id: str
    user_id: str | None
    disease: str | None
    subtype: str | None
    tissue: str | None
    ontology_id: str | None
    ontology_name: str | None
    status: str
    command: str | None
    approach: str | None
    use_snakemake: bool
    storage_path: str
    archived: bool
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass
class JobRecord:
    job_id: str
    run_id: str
    user_id: str | None
    command: str
    status: str
    error: str | None
    log_summary: str | None
    started_at: str | None
    finished_at: str | None
    duration_sec: float | None


@dataclass
class ArtifactRecord:
    run_id: str
    artifact_type: str
    file_path: str
    row_count: int | None
    checksum_sha256: str | None
    recorded_at: str


def run_to_dict(r: RunRecord) -> dict[str, Any]:
    return {
        "run_id": r.run_id,
        "user_id": r.user_id,
        "disease": r.disease,
        "subtype": r.subtype,
        "tissue": r.tissue,
        "ontology_id": r.ontology_id,
        "ontology_name": r.ontology_name,
        "status": r.status,
        "command": r.command,
        "approach": r.approach,
        "use_snakemake": r.use_snakemake,
        "storage_path": r.storage_path,
        "archived": r.archived,
        "error": r.error,
        "created_at": r.created_at,
        "started_at": r.started_at,
        "finished_at": r.finished_at,
    }
