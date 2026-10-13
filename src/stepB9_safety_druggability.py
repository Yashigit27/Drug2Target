"""
Track B / B9 — safety + druggability + structure readiness.

Providers (config track_b.b9.provider):
  - hybrid         : Open Targets tractability + optional PDBe structure (default)
  - ot_tractability: Open Targets only
  - defaults       : constant baseline (legacy)

Uses mygene for symbol→Ensembl. OT knownDrugs is not on current Target API;
chemicalProbes + Approved Drug tractability flags cover chemical precedent.
Safety uses safetyLiabilities, isEssential, and LoF geneticConstraint.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from src.lib.settings import load_config
from src.lib.tractability import score_b9_readiness
from src.lib.track_b.paths import step_b1_path, step_b9_path, track_b_dir


def _b9_label(method_counts: dict[str, int], *, pdbe_enabled: bool) -> str:
    real = sum(
        int(method_counts.get(k, 0))
        for k in ("hybrid", "ot_tractability")
    )
    fallback = sum(int(v) for k, v in method_counts.items() if str(k).startswith("defaults"))
    total = real + fallback
    if real > 0:
        src = "OT+PDBe" if pdbe_enabled else "Open Targets"
        return f"B9: {src} tractability — {real}/{total or real} genes"
    return "B9: defaults only (no OT data)"


def run_step_b9(run_id: str) -> Path:
    p1 = step_b1_path(run_id)
    if not p1.is_file():
        raise FileNotFoundError(f"Run B1 first. Missing: {p1}")
    b1 = pd.read_csv(p1)
    if b1.empty:
        raise ValueError("B1 output empty")

    cfg = load_config().track_b.b9
    out = score_b9_readiness(b1, cfg=cfg)

    out_path = step_b9_path(run_id)
    out.to_csv(out_path, index=False)

    method_counts = (
        out["b9_method"].astype(str).value_counts().to_dict()
        if "b9_method" in out.columns
        else {}
    )
    pdbe_enabled = bool(cfg.use_pdbe) and (cfg.provider or "").lower() == "hybrid"
    label = _b9_label(method_counts, pdbe_enabled=pdbe_enabled)
    summary = {
        "provider_config": cfg.provider,
        "use_pdbe": pdbe_enabled,
        "n_genes": int(len(out)),
        "method_counts": {str(k): int(v) for k, v in method_counts.items()},
        "used_ot": any(k in method_counts for k in ("hybrid", "ot_tractability")),
        "mean_b9_readiness": float(out["b9_readiness_score"].mean())
        if len(out) and "b9_readiness_score" in out.columns
        else None,
        "label": label,
    }
    summary_path = track_b_dir(run_id) / "stepB9_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(label)
    print(f"wrote {out_path} ({len(out)} rows) methods={method_counts}")
    print(f"wrote {summary_path}")
    return out_path


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Track B Step B9 — safety/druggability/structure")
    p.add_argument("--run-id", required=True)
    args = p.parse_args(argv)
    run_step_b9(args.run_id)


if __name__ == "__main__":
    main()
