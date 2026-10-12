"""
Track B / B3 — Co-expression / tissue expression support.

Providers (config track_b.b3.provider):
  - hybrid       : GTEx tissue median TPM + STRING neighborhood (default)
  - gtex_tissue  : GTEx only (STRING fallback per missing gene)
  - string_proxy : legacy B1 neighborhood proxy only

Place GTEx file at:
  data/external/gtex/gene_median_tpm.gct.gz
(or any *gene_median_tpm*.gct.gz in that folder)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.lib.expression import score_b3_coexpression
from src.lib.paths import manifest_path
from src.lib.run_manifest import read_manifest
from src.lib.settings import load_config
from src.lib.track_b.paths import step_b1_path, step_b3_path, track_b_dir


def _tissue_for_run(run_id: str) -> str | None:
    mp = manifest_path(run_id)
    if not mp.is_file():
        return None
    try:
        m = read_manifest(mp)
        return m.input.tissue
    except Exception:
        return None


def _b3_label(method_counts: dict[str, int], gtex_tissue: str | None) -> str:
    """Short human label for UI / summary."""
    gtexish = sum(
        int(method_counts.get(k, 0))
        for k in ("hybrid", "gtex_tissue")
    )
    proxyish = sum(
        int(method_counts.get(k, 0))
        for k in ("string_proxy", "string_proxy_fallback", "gtex_missing")
    )
    total = gtexish + proxyish
    if gtexish > 0 and gtex_tissue:
        return f"B3: GTEx ({gtex_tissue}) — {gtexish}/{total or gtexish} genes"
    if gtexish > 0:
        return f"B3: GTEx used — {gtexish} genes"
    return "B3: STRING proxy only (no GTEx)"


def run_step_b3(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    if b1.empty:
        raise ValueError("B1 output empty")

    tissue = _tissue_for_run(run_id)
    cfg = load_config().track_b.b3
    out = score_b3_coexpression(b1, tissue=tissue, cfg=cfg)

    out_path = step_b3_path(run_id)
    out.to_csv(out_path, index=False)

    method_counts = (
        out["b3_method"].astype(str).value_counts().to_dict()
        if "b3_method" in out.columns
        else {}
    )
    gtex_tissue = None
    if "gtex_tissue" in out.columns:
        non_null = out["gtex_tissue"].dropna()
        if len(non_null):
            gtex_tissue = str(non_null.iloc[0])

    label = _b3_label(method_counts, gtex_tissue)
    summary = {
        "provider_config": cfg.provider,
        "user_tissue": tissue,
        "gtex_tissue": gtex_tissue,
        "n_genes": int(len(out)),
        "method_counts": {str(k): int(v) for k, v in method_counts.items()},
        "used_gtex": any(k in method_counts for k in ("hybrid", "gtex_tissue")),
        "label": label,
    }
    summary_path = track_b_dir(run_id) / "stepB3_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(label)
    print(f"wrote {out_path} ({len(out)} rows) methods={method_counts}")
    print(f"wrote {summary_path}")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B3 — coexpression / tissue expression")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b3(args.run_id)


if __name__ == "__main__":
    main()
