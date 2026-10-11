"""SQLite connection and schema for the D2T registry."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from threading import RLock
from typing import Iterator

from src.lib.settings import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    user_id TEXT,
    disease TEXT,
    subtype TEXT,
    tissue TEXT,
    ontology_id TEXT,
    ontology_name TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    command TEXT,
    approach TEXT,
    use_snakemake INTEGER NOT NULL DEFAULT 0,
    storage_path TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    user_id TEXT,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    log_summary TEXT,
    started_at TEXT,
    finished_at TEXT,
    duration_sec REAL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    row_count INTEGER,
    checksum_sha256 TEXT,
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_runs_user ON runs(user_id);
CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_run ON jobs(run_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_run ON artifacts(run_id);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

_lock = RLock()
_initialized = False


def registry_db_path() -> Path:
    cfg = load_config()
    rel = getattr(cfg.paths, "registry_db", None) or os.environ.get(
        "D2T_REGISTRY_DB", "storage/registry/d2t_registry.db"
    )
    path = _repo_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(registry_db_path()), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    with _lock:
        conn = get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_db() -> None:
    global _initialized
    with _lock:
        if _initialized:
            return
        with db_session() as conn:
            conn.executescript(_SCHEMA)
        _initialized = True
