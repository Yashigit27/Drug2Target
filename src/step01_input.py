"""
Step 1 — capture disease / subtype / tissue (human-only) and resolve ontology id.

Writes:
  outputs/<run_id>/manifest.json
  outputs/<run_id>/inputs.json   (duplicate of input block for quick inspection)
"""

from __future__ import annotations

import argparse
import uuid
from datetime import datetime, timezone

import httpx

from src import __version__
from src.lib.http_client import make_http_client
from src.lib.models import DiseaseHit, DiseaseResolution, Manifest, RunInput
from src.lib.opentargets_client import fetch_disease_header, search_diseases
from src.lib.paths import ensure_run_dir, inputs_path, manifest_path
from src.lib.run_manifest import write_manifest


def _select_candidate(
    candidates: list[DiseaseHit],
    disease_label: str,
    disease_subtype: str | None,
) -> tuple[DiseaseHit, bool, str | None]:
    if not candidates:
        raise ValueError("No disease ontology hits returned; try a simpler disease name or pass --disease-id.")

    ambiguous = len(candidates) > 1
    note: str | None = None
    if ambiguous:
        note = (
            "Multiple ontology hits returned; picked the best heuristic match. "
            "Re-run with --disease-id MONDO_... or EFO_... from the candidate list to pin the term."
        )

    selected = candidates[0]
    if disease_subtype:
        key = disease_subtype.lower()
        for c in candidates:
            if key in c.name.lower() or key in (c.description or "").lower():
                selected = c
                break
    else:
        # Prefer exact name match (case-insensitive) when possible
        dl = disease_label.strip().lower()
        for c in candidates:
            if c.name.strip().lower() == dl:
                selected = c
                break

    return selected, ambiguous, note


def run_step1(
    inp: RunInput,
    *,
    disease_id_override: str | None = None,
    run_id: str | None = None,
) -> Manifest:
    if inp.species != "human":
        raise ValueError("This project is human-only; species must be 'human'.")

    rid = run_id or str(uuid.uuid4())
    ensure_run_dir(rid)

    with make_http_client() as client:
        if disease_id_override:
            hit = fetch_disease_header(disease_id_override.strip(), client=client)
            resolution = DiseaseResolution(
                query_used=disease_id_override.strip(),
                candidates=[hit],
                selected=hit,
                ambiguous=False,
                note="Disease id provided explicitly; search skipped.",
            )
        else:
            # Search with the primary label only; mixing subtype into the search string
            # often pulls unrelated ontology hits. Subtype is applied in `_select_candidate`.
            query_used = inp.disease_label.strip()
            hits = search_diseases(query_used, client=client)
            selected, ambiguous, note = _select_candidate(hits, inp.disease_label, inp.disease_subtype)
            if inp.disease_subtype and note is None and len(hits) > 1:
                note = (
                    f"Subtype hint {inp.disease_subtype!r} used to choose among "
                    f"{len(hits)} ontology candidates from search {query_used!r}."
                )
            resolution = DiseaseResolution(
                query_used=query_used,
                candidates=hits,
                selected=selected,
                ambiguous=ambiguous,
                note=note,
            )

    manifest = Manifest(
        run_id=rid,
        pipeline_version=__version__,
        input=inp,
        disease_resolution=resolution,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    write_manifest(manifest_path(rid), manifest)
    inputs_path(rid).write_text(
        inp.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> Manifest:
    p = argparse.ArgumentParser(description="Step 1 — disease / subtype / tissue input + ontology resolution")
    p.add_argument("--disease", required=True, help="Primary disease name (human)")
    p.add_argument("--subtype", default=None, help="Optional disease subtype / modifier")
    p.add_argument("--tissue", default=None, help="Optional tissue / anatomical context (stored for later steps)")
    p.add_argument(
        "--disease-id",
        default=None,
        help="Optional Open Targets disease id (e.g. MONDO_0004975) to skip search ambiguity",
    )
    p.add_argument("--run-id", default=None, help="Optional run UUID; generated if omitted")
    args = p.parse_args(argv)

    inp = RunInput(
        disease_label=args.disease,
        disease_subtype=args.subtype,
        tissue=args.tissue,
        species="human",
    )  
    manifest = run_step1(inp, disease_id_override=args.disease_id, run_id=args.run_id)
    print(f"run_id={manifest.run_id}")
    print(f"selected_disease={manifest.disease_resolution.selected.id} {manifest.disease_resolution.selected.name}")
    if manifest.disease_resolution.note:
        print(f"note={manifest.disease_resolution.note}")
    print(f"wrote {manifest_path(manifest.run_id)}")
    return manifest


if __name__ == "__main__":
    main()
