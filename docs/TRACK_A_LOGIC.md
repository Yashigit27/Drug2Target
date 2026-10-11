# Track A — Underexplored Known Targets

Track A is built to run **after Step 1 + Step 2**.

Prerequisite:
- `outputs/<run_id>/manifest.json` from `step1`
- `outputs/<run_id>/artifacts/known_disease_genes.csv` from `step2`

---

## Step A1 — Saturation / Crowdedness

Script: `src/stepA1_saturation.py`

What it does:
1. Loads known disease-linked rows (`association_score` not null).
2. Keeps top `track_a.top_n_for_analysis` by association score.
3. For each target:
   - Europe PMC disease+gene publication hit count.
   - Open Targets target profile (tractability + protein IDs).
4. Builds crowdedness features:
   - `publication_count`
   - `approved_drug_flag`
   - `clinical_flag`
   - `ligand_flag`
5. Computes `crowded_score` (weighted; config driven).

Output:
- `outputs/<run_id>/artifacts/track_a/stepA1_saturation.csv`

---

## Step A2 — Downweight Overworked Targets

Script: `src/stepA2_downweight.py`

What it does:
1. Reads A1 output.
2. Uses crowded score quantiles from config:
   - `crowded_high_quantile`
   - `crowded_extreme_quantile`
3. Applies penalty (`crowded_penalty`) and action labels:
   - `keep`
   - `moderate_downweight`
   - `strong_downweight`
4. Produces `downweighted_association_score`.

Output:
- `outputs/<run_id>/artifacts/track_a/stepA2_downweighted.csv`

---

## Step A3 — Biological Relevance Re-scoring

Script: `src/stepA3_relevance.py`

What it does:
1. Merges A2 with merged Step2 evidence columns.
2. Computes normalized evidence:
   - `disease_evidence_norm` (from association score)
   - `literature_support_norm`
3. Uses heuristic text relevance:
   - `tissue_relevance_score` (snippet contains tissue keyword)
   - `subtype_relevance_score` (snippet contains subtype keyword)
4. Produces `biological_relevance_score`.

Output:
- `outputs/<run_id>/artifacts/track_a/stepA3_relevance.csv`

---

## Step A4 — CADD Readiness

Script: `src/stepA4_cadd_readiness.py`

What it does:
1. Reuses A1-derived tractability proxies.
2. Computes CADD readiness features:
   - `structure_with_ligand_flag`
   - `pocketability_flag`
   - `ligand_precedent_flag`
   - `swissprot_flag`
   - `druggable_family_flag`
3. Produces `cadd_readiness_score`.

Output:
- `outputs/<run_id>/artifacts/track_a/stepA4_cadd_readiness.csv`

---

## Step A5 — Final Known Target Ranking

Script: `src/stepA5_rank.py`

What it does:
1. Merges A2 + A3 + A4.
2. Computes `low_crowdedness_score = 1 - crowded_score`.
3. Final weighted score (config `track_a.final_ranking_weights`):
   - biological relevance
   - CADD readiness
   - tissue relevance
   - low crowdedness
4. Produces ranked output and reasons.

Output:
- `outputs/<run_id>/artifacts/track_a/ranked_known_targets.csv`

---

## Convenience Runner

Script: `src/stepA_run_all.py`

Runs:
- A1 → A2 → A3 → A4 → A5

CLI:
- `python -m src.cli trackA --run-id <run_id>`

Or stepwise:
- `python -m src.cli stepA1 --run-id <run_id>`
- `python -m src.cli stepA2 --run-id <run_id>`
- `python -m src.cli stepA3 --run-id <run_id>`
- `python -m src.cli stepA4 --run-id <run_id>`
- `python -m src.cli stepA5 --run-id <run_id>`
