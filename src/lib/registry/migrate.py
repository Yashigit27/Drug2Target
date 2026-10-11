"""Import legacy outputs/ runs into the registry on startup."""

from __future__ import annotations

from pathlib import Path

from src.lib.paths import outputs_dir
from src.lib.registry.repository import create_run, get_run
from src.lib.registry.storage_layout import legacy_outputs_rel
from src.lib.run_manifest import read_manifest


def migrate_legacy_runs() -> int:
    """Register existing outputs/<run_id>/ folders not yet in DB."""
    root = outputs_dir()
    if not root.is_dir():
        return 0
    imported = 0
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        run_id = p.name
        if get_run(run_id):
            continue
        manifest_path = p / "manifest.json"
        disease = subtype = tissue = ontology_id = ontology_name = None
        created_at = None
        status = "completed" if (p / "artifacts" / "known_disease_genes.csv").is_file() else "unknown"
        if manifest_path.is_file():
            try:
                m = read_manifest(manifest_path)
                disease = m.input.disease_label
                subtype = m.input.disease_subtype
                tissue = m.input.tissue
                ontology_id = m.disease_resolution.selected.id
                ontology_name = m.disease_resolution.selected.name
                created_at = m.created_at
            except Exception:
                pass
        if not created_at:
            from datetime import datetime, timezone

            created_at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()

        rel = legacy_outputs_rel(run_id)
        create_run(
            run_id,
            rel,
            user_id=None,
            disease=disease,
            subtype=subtype,
            tissue=tissue,
            command="legacy",
            approach=None,
            use_snakemake=(p / "snakemake_runtime.yaml").is_file(),
            created_at=created_at,
        )
        from src.lib.registry.repository import update_run

        update_run(
            run_id,
            status=status,
            ontology_id=ontology_id,
            ontology_name=ontology_name,
        )
        imported += 1
    return imported
