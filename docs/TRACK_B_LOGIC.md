# Track B — Novel Candidate Discovery

This document explains how Track B is implemented in code, step-by-step, and how each step maps to your scientific pipeline.

Track B starts **after**:
- `step1` (manifest with disease/subtype/tissue)
- `step2` (merged known targets with literature evidence)

Main objective:
- Discover **new plausible candidates** near disease biology.

---

## Design Principles

1. **Modular scripts per step** (B1 ... B10)
2. **Run-local artifacts** under `outputs/<run_id>/artifacts/track_b/`
3. **Transparent proxy layers** where heavy datasets are not yet integrated
4. **Config-driven scoring weights** in `config/default.yaml` under `track_b`

---

## File Map

### Step scripts
- `src/stepB1_seed_expansion.py`
- `src/stepB2_functional_similarity.py`
- `src/stepB3_coexpression.py`
- `src/stepB4_differential_expression.py`
- `src/stepB5_pathway.py`
- `src/stepB6_genetic_support.py`
- `src/stepB7_network_prioritization.py`
- `src/stepB8_novelty.py`
- `src/stepB9_safety_druggability.py`
- `src/stepB10_rank.py`
- `src/stepB_run_all.py`

### Helpers
- `src/lib/track_b/paths.py`
- `src/lib/track_b/scoring.py`
- `src/lib/track_b/sources.py`

### Config
- `src/lib/settings.py` (`TrackBConfig`)
- `config/default.yaml` (`track_b:` block)

---

## Data Contract

Input to Track B:
- `outputs/<run_id>/artifacts/known_disease_genes.csv`

Final output:
- `outputs/<run_id>/artifacts/track_b/ranked_novel_candidates.csv`

Intermediate outputs (one per step) are always saved for inspection.

---

## Step-by-step logic

## B1 — Seed Network Expansion
Script: `src/stepB1_seed_expansion.py`

Scientific idea:
- Expand from known disease targets to network neighbors.

Implementation:
1. Read known targets (`association_score` rows) from Step2 output.
2. Keep top `track_b.seed_top_n` as seeds.
3. Query STRING `interaction_partners` for each seed.
4. Filter out original seed nodes.
5. Aggregate candidate-level metrics:
   - `seed_count`
   - `mean_string_score`
   - `max_string_score`
6. Keep top `track_b.top_candidates_for_scoring`.

Output:
- `stepB1_candidate_neighbors.csv`

Note:
- Current implementation uses **STRING** as primary network source.
- BioGRID/IntAct hooks can be added later in the same step and merged under `source_db`.

---

## B2 — Functional Similarity
Script: `src/stepB2_functional_similarity.py`

Scientific idea:
- Candidates similar in GO/pathway/domain to seed biology are stronger.

Implementation:
1. Collect seed + candidate symbols.
2. Fetch annotations from mygene:
   - GO BP IDs
   - Reactome pathway IDs
   - InterPro domain IDs
3. Build union sets from seeds.
4. For each candidate compute:
   - GO Jaccard
   - pathway overlap Jaccard
   - domain Jaccard
5. Weighted functional score:
   - GO 0.4, pathway 0.4, domain 0.2

Output:
- `stepB2_functional_similarity.csv`

---

## B3 — Co-expression / tissue expression
Script: `src/stepB3_coexpression.py`  
Helpers: `src/lib/expression/` (`b3.py`, `gtex_lookup.py`, `string_proxy.py`)

Scientific idea:
- Candidates expressed in the disease-relevant tissue (and/or near seeds) gain support.

Implementation (config `track_b.b3.provider`):
1. **hybrid** (default): GTEx median TPM in mapped user tissue + STRING neighborhood blend.
2. **gtex_tissue**: GTEx primary; STRING only if gene/tissue missing.
3. **string_proxy**: legacy `0.6*seed_count + 0.4*mean_string_score` only.

Data:
- Optional local file `data/external/gtex/gene_median_tpm.gct.gz` (see that folder README).
- If GTEx file is absent, B3 safely falls back to STRING proxy.

Output:
- `stepB3_coexpression.csv` with `coexpression_proxy_score` (B10 contract) plus
  `b3_method`, optional `tissue_tpm`, `gtex_tissue`, `ensembl_gene_id`.

Future upgrade:
- Sample-level GTEx correlation of candidate ↔ seed genes (larger matrices).

---

## B4 — Differential Expression
Script: `src/stepB4_differential_expression.py`

Scientific idea:
- Dysregulated genes in disease tissue are prioritized.

Current implementation (proxy):
1. For each candidate, query Europe PMC hitCount for:
   - disease + gene + (upregulated/downregulated/overexpression/underexpression)
2. Log-normalize counts to `differential_expression_score`.

Output:
- `stepB4_differential_expression.csv`

Future upgrade:
- Integrate real DE tables from GEO/TCGA contrasts.

---

## B5 — Pathway Enrichment / Relevance
Script: `src/stepB5_pathway.py`

Scientific idea:
- Candidates inside disease-relevant pathways gain support.

Implementation:
1. Build seed pathway universe from mygene Reactome IDs.
2. For each candidate compute:
   - `candidate_pathway_count`
   - `pathway_overlap_count`
   - `pathway_relevance_score = overlap / candidate_pathway_count`

Output:
- `stepB5_pathway_enrichment.csv`

---

## B6 — Genetic Support
Script: `src/stepB6_genetic_support.py`

Scientific idea:
- Genetic disease evidence increases credibility.

Current implementation:
1. Reuse disease association evidence from Step2 merged table.
2. Map candidate symbols to max `association_score` if present.
3. Min-max normalize to `genetic_support_score`.

Output:
- `stepB6_genetic_support.csv`

Future upgrade:
- Direct GWAS/eQTL/mutation burden ingestion.

---

## B7 — Network Prioritization
Script: `src/stepB7_network_prioritization.py`

Scientific idea:
- Central/proximal module nodes are stronger disease hypotheses.

Implementation:
1. Build graph from B1 candidate supports (hub-linked representation).
2. Compute:
   - `proximity_to_seed`
   - `betweenness`
   - `closeness`
3. Combined:
   - `network_prioritization_score = 0.5*proximity + 0.25*betweenness + 0.25*closeness`

Output:
- `stepB7_network_prioritization.csv`

---

## B8 — Novelty Filter
Script: `src/stepB8_novelty.py`

Scientific idea:
- Prefer weakly exploited candidates.

Implementation:
1. Disease-specific publication count per gene via Europe PMC hitCount.
2. Normalize publication crowdedness.
3. Compute `novelty_score` as inverse crowdedness (with placeholders for drug/clinical flags).

Output:
- `stepB8_novelty.csv`

Future upgrade:
- Add direct approved drugs / clinical trials / patent features.

---

## B9 — Safety + Druggability + Structure
Script: `src/stepB9_safety_druggability.py`  
Helpers: `src/lib/tractability/` (`b9.py`, `scoring.py`, `pdbe.py`, `defaults.py`)

Scientific idea:
- Novel target should still be tractable/safe enough for CADD.

Implementation (config `track_b.b9.provider`):
1. **hybrid** (default): mygene symbol→Ensembl → Open Targets tractability /
   chemicalProbes / safetyLiabilities / isEssential / LoF constraint, plus
   optional **PDBe** experimental structure via UniProt accession.
2. **ot_tractability**: Open Targets only (no PDBe).
3. **defaults**: legacy constant scores (fallback on API failure).

Notes:
- Current OT GraphQL has no `target.knownDrugs`; Approved Drug tractability
  flags + `chemicalProbes` cover chemical/clinical precedent.
- AlphaFold presence is intentionally not used (too common to rank).

Output:
- `stepB9_safety_druggability.csv` (`b9_readiness_score` for B10)
- `stepB9_summary.json` (UI badge provenance)

---

## B10 — Final Novel Ranking
Script: `src/stepB10_rank.py`

Scientific idea:
- Fuse orthogonal evidence into final novel candidate ranking.

Implementation:
1. Merge outputs from B2/B3/B4/B5/B7/B8/B9.
2. Compute weighted final score using `track_b.final_ranking_weights`:
   - network support
   - pathway relevance
   - expression evidence
   - coexpression
   - literature weak support (novelty)
   - druggability
3. Save rank + score breakdown + reason string.

Output:
- `ranked_novel_candidates.csv`

---

## CLI

Stepwise:
- `python -m src.cli stepB1 --run-id <run_id>`
- ...
- `python -m src.cli stepB10 --run-id <run_id>`

End-to-end:
- `python -m src.cli trackB --run-id <run_id>`

---

## How this maps to your scientific Track B plan

- B1: network expansion ✅
- B2: functional similarity ✅
- B3: coexpression (proxy now, matrix-based later) ✅
- B4: differential expression (literature proxy now) ✅
- B5: pathway relevance ✅
- B6: genetic support ✅
- B7: network prioritization ✅
- B8: novelty filter ✅
- B9: safety/druggability/structure (baseline now) ✅
- B10: final ranking ✅

This gives you a complete runnable Track B with clean architecture and inspectable artifacts, while keeping clear upgrade points for stronger omics/genetics integrations.
