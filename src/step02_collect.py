"""
Step 2 — collect disease-associated genes from:
  1) Open Targets Platform (disease -> target associations)
  2) Literature RAG: Europe PMC -> TF-IDF chunk retrieval -> gene extraction -> mygene validation

Then: normalize (via Ensembl ids where present), merge, dedupe, save combined table.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

from src.lib.gene_merge import merge_opentargets_and_literature
from src.lib.http_client import make_http_client
from src.lib.literature_rag_run import run_literature_rag
from src.lib.opentargets_client import cache_raw_json, iter_associated_targets
from src.lib.paths import manifest_path, raw_dir, run_dir
from src.lib.run_manifest import read_manifest
from src.lib.settings import load_config


def associations_to_dataframe(disease_meta: dict, rows: list[dict]) -> pd.DataFrame:
    records: list[dict] = []
    disease_id = disease_meta.get("id")
    disease_name = disease_meta.get("name")
    for r in rows:
        tgt = r.get("target") or {}
        records.append(
            {
                "source": "open_targets",
                "disease_ot_id": disease_id,
                "disease_name": disease_name,
                "ensembl_gene_id": tgt.get("id"),
                "gene_symbol": tgt.get("approvedSymbol"),
                "association_score": r.get("score"),
            }
        )
    return pd.DataFrame.from_records(records)


def run_step2(run_id: str, *, skip_literature: bool = False) -> dict[str, Any]:
    mpath = manifest_path(run_id)
    if not mpath.is_file():
        raise FileNotFoundError(f"Missing manifest for run_id={run_id!r}: {mpath}")

    manifest = read_manifest(mpath)
    disease_id = manifest.disease_resolution.selected.id

    cfg = load_config()
    lit_on = (
        cfg.literature_rag.enabled
        and not skip_literature
        and os.environ.get("LITERATURE_RAG_ENABLED", "true").lower() not in ("0", "false", "no")
    )

    raw_dir_path = raw_dir(run_id)
    raw_dir_path.mkdir(parents=True, exist_ok=True)

    out_dir = run_dir(run_id) / "artifacts"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "known_disease_genes.csv"
    summary_path = out_dir / "step2_summary.json"

    for stale in (csv_path, summary_path, raw_dir_path / "literature_rag_summary.json"):
        if stale.is_file():
            stale.unlink()

    with make_http_client() as client:
        disease_meta, rows = iter_associated_targets(disease_id, client=client)

    cache_raw_json(raw_dir_path / "open_targets_associations_raw.json", {"disease": disease_meta, "rows": rows})

    df_ot = associations_to_dataframe(disease_meta, rows)
    if not df_ot.empty:
        df_ot = df_ot.sort_values("association_score", ascending=False)
        df_ot = df_ot.drop_duplicates(subset=["ensembl_gene_id"], keep="first")

    lit_rows: list[dict] = []
    lit_cache: dict[str, Any] = {}
    if lit_on:
        lit_rows, lit_cache = run_literature_rag(manifest)
        cache_raw_json(raw_dir_path / "literature_rag_summary.json", lit_cache)

    merged = merge_opentargets_and_literature(
        df_ot,
        lit_rows,
        disease_ot_id=str(disease_meta.get("id")),
        disease_name=str(disease_meta.get("name")),
    )
    merged.to_csv(csv_path, index=False)

    lit_only = int((merged["source"] == "literature_rag").sum()) if not merged.empty else 0
    lit_merged = int((merged["source"] == "open_targets+literature_rag").sum()) if not merged.empty else 0

    summary: dict[str, Any] = {
        "literature_enabled": lit_on,
        "literature_skipped": skip_literature,
        "open_targets_rows": int(len(df_ot)),
        "literature_gene_rows": int(len(lit_rows)),
        "literature_only_genes": lit_only,
        "literature_merged_genes": lit_merged,
        "merged_rows": int(len(merged)),
        "literature_rag": lit_cache if lit_on else None,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"wrote {csv_path} ({len(merged)} rows)")
    if lit_on:
        print(
            f"  literature_rag: articles={lit_cache.get('article_count', 0)} "
            f"validated_gene_hits={lit_cache.get('literature_row_count', 0)}"
        )
    return {"csv_path": str(csv_path), **summary}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Step 2 - Open Targets + optional literature RAG")
    p.add_argument("--run-id", required=True, help="Run id produced by step 1")
    p.add_argument(
        "--skip-literature",
        action="store_true",
        help="Skip Europe PMC / TF-IDF / mygene literature branch (Open Targets only)",
    )
    args = p.parse_args(argv)
    run_step2(args.run_id, skip_literature=args.skip_literature)


if __name__ == "__main__":
    main()
