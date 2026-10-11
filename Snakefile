import subprocess
import sys

configfile: "config/snakemake.yaml"

RUN_ID = config["run_id"]
OUT_BASE = config.get("output_base") or f"outputs/{RUN_ID}"


def _cfg_str(key: str) -> str | None:
    val = config.get(key)
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def _final_outputs(_wildcards):
    outs = []
    if config.get("run_track_a", True):
        outs.append(f"{OUT_BASE}/artifacts/track_a/ranked_known_targets.csv")
    if config.get("run_track_b", True):
        outs.append(f"{OUT_BASE}/artifacts/track_b/ranked_novel_candidates.csv")
    if config.get("run_fusion", True):
        outs.append(f"{OUT_BASE}/artifacts/fusion/unified_target_portfolio.csv")
    if not outs:
        raise ValueError("At least one of run_track_a/run_track_b/run_fusion must be true.")
    return outs


def _run_cli(*args: str) -> None:
    cmd = [sys.executable, "-m", "src.cli", *args]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)


rule all:
    input:
        _final_outputs


rule step1:
    output:
        manifest=f"{OUT_BASE}/manifest.json",
        inputs=f"{OUT_BASE}/inputs.json",
    run:
        disease = _cfg_str("disease")
        if not disease:
            raise ValueError("config['disease'] is required")
        args = ["step1", "--disease", disease, "--run-id", RUN_ID]
        subtype = _cfg_str("subtype")
        tissue = _cfg_str("tissue")
        disease_id = _cfg_str("disease_id")
        if subtype:
            args += ["--subtype", subtype]
        if tissue:
            args += ["--tissue", tissue]
        if disease_id:
            args += ["--disease-id", disease_id]
        _run_cli(*args)


rule step2:
    input:
        manifest=rules.step1.output.manifest
    output:
        known=f"{OUT_BASE}/artifacts/known_disease_genes.csv",
        summary=f"{OUT_BASE}/artifacts/step2_summary.json",
    run:
        args = ["step2", "--run-id", RUN_ID]
        if bool(config.get("skip_literature", False)):
            args.append("--skip-literature")
        _run_cli(*args)


rule track_a:
    input:
        rules.step2.output.known
    output:
        ranked=f"{OUT_BASE}/artifacts/track_a/ranked_known_targets.csv"
    run:
        _run_cli("trackA", "--run-id", RUN_ID)


rule track_b:
    input:
        rules.step2.output.known
    output:
        ranked=f"{OUT_BASE}/artifacts/track_b/ranked_novel_candidates.csv"
    run:
        _run_cli("trackB", "--run-id", RUN_ID)


def _f1_inputs(_wildcards):
    ins = [rules.step2.output.known]
    if config.get("run_track_a", True):
        ins.append(rules.track_a.output.ranked)
    if config.get("run_track_b", True):
        ins.append(rules.track_b.output.ranked)
    return ins


rule step_f1:
    input:
        _f1_inputs
    output:
        portfolio=f"{OUT_BASE}/artifacts/fusion/unified_target_portfolio.csv",
        summary=f"{OUT_BASE}/artifacts/fusion/fusion_summary.json",
    run:
        _run_cli("stepF1", "--run-id", RUN_ID)
