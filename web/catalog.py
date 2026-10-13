"""Pipeline feature catalog for the web UI."""

from __future__ import annotations

PIPELINE_LAYERS = [
    {
        "id": "foundation",
        "title": "Foundation",
        "subtitle": "Disease input and target collection",
        "color": "#3b82f6",
        "steps": [
            {
                "id": "step1",
                "name": "Step 1 - Disease Input",
                "script": "step01_input.py",
                "summary": "Resolve disease via Open Targets (MONDO/EFO), mint run_id.",
                "outputs": ["manifest.json", "inputs.json"],
                "apis": ["Open Targets GraphQL"],
            },
            {
                "id": "step2",
                "name": "Step 2 - Target Collection",
                "script": "step02_collect.py",
                "summary": "Open Targets associations + optional Europe PMC literature RAG merge.",
                "outputs": ["known_disease_genes.csv", "step2_summary.json"],
                "apis": ["Open Targets", "Europe PMC", "mygene"],
            },
        ],
    },
    {
        "id": "track_a",
        "title": "Track A",
        "subtitle": "Underexplored known targets",
        "color": "#10b981",
        "steps": [
            {"id": "stepA1", "name": "A1 - Saturation", "script": "stepA1_saturation.py", "summary": "Crowdedness: publication counts + tractability flags.", "outputs": ["track_a/stepA1_saturation.csv"]},
            {"id": "stepA2", "name": "A2 - Downweight", "script": "stepA2_downweight.py", "summary": "Penalize overworked, highly studied targets.", "outputs": ["track_a/stepA2_downweighted.csv"]},
            {"id": "stepA3", "name": "A3 - Relevance", "script": "stepA3_relevance.py", "summary": "Biological relevance: disease score, literature, tissue heuristics.", "outputs": ["track_a/stepA3_relevance.csv"]},
            {"id": "stepA4", "name": "A4 - CADD Readiness", "script": "stepA4_cadd_readiness.py", "summary": "Structure/ligand tractability proxies for CADD.", "outputs": ["track_a/stepA4_cadd_readiness.csv"]},
            {"id": "stepA5", "name": "A5 - Final Rank", "script": "stepA5_rank.py", "summary": "Weighted fusion to ranked known targets.", "outputs": ["track_a/ranked_known_targets.csv"]},
        ],
    },
    {
        "id": "track_b",
        "title": "Track B",
        "subtitle": "Novel candidate discovery",
        "color": "#8b5cf6",
        "steps": [
            {"id": "stepB1", "name": "B1 - STRING Expansion", "script": "stepB1_seed_expansion.py", "summary": "PPI network neighbors from top disease seeds.", "outputs": ["track_b/stepB1_candidate_neighbors.csv"], "apis": ["STRING"]},
            {"id": "stepB2", "name": "B2 - Functional Similarity", "script": "stepB2_functional_similarity.py", "summary": "GO / pathway / domain Jaccard vs seeds.", "outputs": ["track_b/stepB2_functional_similarity.csv"], "apis": ["mygene"]},
            {"id": "stepB3", "name": "B3 - Coexpression", "script": "stepB3_coexpression.py", "summary": "GTEx tissue expression (hybrid) with STRING fallback.", "outputs": ["track_b/stepB3_coexpression.csv"]},
            {"id": "stepB4", "name": "B4 - Differential Expression", "script": "stepB4_differential_expression.py", "summary": "DE evidence proxy via Europe PMC keywords.", "outputs": ["track_b/stepB4_differential_expression.csv"], "apis": ["Europe PMC"]},
            {"id": "stepB5", "name": "B5 - Pathway Relevance", "script": "stepB5_pathway.py", "summary": "Reactome+KEGG pathway overlap weighted by seed recurrence.", "outputs": ["track_b/stepB5_pathway_enrichment.csv"], "apis": ["mygene"]},
            {"id": "stepB6", "name": "B6 - Genetic Support", "script": "stepB6_genetic_support.py", "summary": "Association scores from Step 2 for candidates.", "outputs": ["track_b/stepB6_genetic_support.csv"]},
            {"id": "stepB7", "name": "B7 - Network Priority", "script": "stepB7_network_prioritization.py", "summary": "Centrality + proximity on disease-module graph.", "outputs": ["track_b/stepB7_network_prioritization.csv"]},
            {"id": "stepB8", "name": "B8 - Novelty", "script": "stepB8_novelty.py", "summary": "Low literature frequency gives higher novelty.", "outputs": ["track_b/stepB8_novelty.csv"], "apis": ["Europe PMC"]},
            {"id": "stepB9", "name": "B9 - Druggability", "script": "stepB9_safety_druggability.py", "summary": "OT tractability + PDBe structure + safety liabilities.", "outputs": ["track_b/stepB9_safety_druggability.csv"], "apis": ["Open Targets", "mygene", "PDBe"]},
            {"id": "stepB10", "name": "B10 - Final Rank", "script": "stepB10_rank.py", "summary": "Weighted fusion to ranked novel candidates.", "outputs": ["track_b/ranked_novel_candidates.csv"]},
        ],
    },
    {
        "id": "fusion",
        "title": "Fusion",
        "subtitle": "Unified CADD-ready portfolio",
        "color": "#f59e0b",
        "steps": [
            {
                "id": "stepF1",
                "name": "F1 - Unified Portfolio",
                "script": "stepF1_fusion.py",
                "summary": "Merge Track A + B into tiered, deduplicated target portfolio.",
                "outputs": ["fusion/unified_target_portfolio.csv", "fusion/fusion_summary.json"],
            },
        ],
    },
]

RUN_MODES = [
    {"id": "full", "label": "Full pipeline", "steps": ["step1", "step2", "trackA", "trackB", "stepF1"]},
    {"id": "foundation", "label": "Foundation only", "steps": ["step1", "step2"]},
    {"id": "trackA", "label": "Track A only", "steps": ["trackA"]},
    {"id": "trackB", "label": "Track B only", "steps": ["trackB"]},
    {"id": "custom", "label": "Single step", "steps": []},
]

APPROACH_MODES = {
    "both": {"label": "Dual track (A + B)", "steps": ["step1", "step2", "trackA", "trackB", "stepF1"]},
    "track_a": {"label": "Track A only", "steps": ["step1", "step2", "trackA", "stepF1"]},
    "track_b": {"label": "Track B only", "steps": ["step1", "step2", "trackB", "stepF1"]},
}

ARTIFACT_CHECKS = {
    "manifest": "manifest.json",
    "inputs": "inputs.json",
    "known_genes": "artifacts/known_disease_genes.csv",
    "step2_summary": "artifacts/step2_summary.json",
    "track_a_final": "artifacts/track_a/ranked_known_targets.csv",
    "track_b_final": "artifacts/track_b/ranked_novel_candidates.csv",
    "fusion_portfolio": "artifacts/fusion/unified_target_portfolio.csv",
    "fusion_summary": "artifacts/fusion/fusion_summary.json",
}
