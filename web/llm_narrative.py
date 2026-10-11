"""Optional LLM narrative grounded in pipeline literature evidence."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.lib.settings import load_config
from web.evidence import build_evidence_card


def _fallback_narrative(card: dict[str, Any]) -> str:
    gene = card.get("gene_symbol", "?")
    disease = card.get("disease", "?")
    tissue = card.get("tissue") or "unspecified tissue"
    lit = card.get("literature") or {}
    pmids = lit.get("pmids") or []
    fusion = card.get("fusion") or {}
    tier = fusion.get("tier") or "Not in fusion portfolio"
    parts = [
        f"{gene} was evaluated in the {disease} D2T run with tissue context '{tissue}'.",
        f"Fusion tier: {tier}.",
    ]
    if pmids:
        parts.append(f"Literature support includes PMIDs: {', '.join(pmids[:5])}.")
    if lit.get("snippet"):
        parts.append(f"Evidence snippet: {lit['snippet'][:280]}...")
    ta = card.get("track_a")
    tb = card.get("track_b")
    if ta:
        parts.append(f"Track A rank {ta.get('rank')} with score {ta.get('final_known_track_a_score')}.")
    if tb:
        parts.append(f"Track B rank {tb.get('rank')} with score {tb.get('final_novel_score')}.")
    return " ".join(parts)


def generate_gene_narrative(run_id: str, gene: str) -> dict[str, Any]:
    cfg = load_config().llm
    card = build_evidence_card(run_id, gene)
    lit = card.get("literature") or {}
    pmids = lit.get("pmids") or []

    result: dict[str, Any] = {
        "run_id": run_id,
        "gene_symbol": gene.upper(),
        "llm_used": False,
        "pmids_cited": pmids[:10],
        "narrative": _fallback_narrative(card),
    }

    if not cfg.enabled:
        return result

    api_key = os.environ.get(cfg.api_key_env, "").strip()
    if not api_key:
        result["note"] = f"Set {cfg.api_key_env} to enable LLM narrative."
        return result

    base_url = os.environ.get(cfg.base_url_env, "https://api.openai.com/v1").rstrip("/")
    prompt = (
        "Write a concise scientific target summary (120-180 words) for a disease-to-target report. "
        "Use ONLY the structured evidence below. Cite PMIDs inline when present. "
        "Do not invent genes, scores, or citations.\n\n"
        f"Evidence JSON:\n{card}"
    )
    payload = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "You are a careful bioinformatics analyst."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": cfg.max_tokens,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
            r.raise_for_status()
            data = r.json()
            text = data["choices"][0]["message"]["content"].strip()
            result["narrative"] = text
            result["llm_used"] = True
            result["model"] = cfg.model
    except Exception as exc:
        result["note"] = f"LLM call failed: {exc}"

    return result


def generate_run_narrative(run_id: str, *, top_n: int = 5) -> dict[str, Any]:
    from src.lib.fusion.paths import step_f1_portfolio_path
    import pandas as pd

    path = step_f1_portfolio_path(run_id)
    genes: list[str] = []
    if path.is_file():
        df = pd.read_csv(path).head(top_n)
        genes = [str(g) for g in df["gene_symbol"].tolist()]
    else:
        from src.lib.track_a.paths import step_a5_path

        ta = step_a5_path(run_id)
        if ta.is_file():
            genes = pd.read_csv(ta).head(top_n)["gene_symbol"].astype(str).tolist()

    sections = [generate_gene_narrative(run_id, g) for g in genes]
    return {"run_id": run_id, "sections": sections}
