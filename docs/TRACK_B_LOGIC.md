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
   - Reactome + KEGG pathway IDs
   - InterPro domain IDs
3. Build union sets from seeds.
4. For each candidate compute:
   - GO Jaccard
   - pathway overlap Jaccard
   - domain Jaccard
5. Weighted functional score:
   - GO 0.4, pathway 0.4, domain 0.2
6. B10 reads `functional_similarity_score` at weight 0.08. Overlap with the pooled terms of every known gene is a very small fraction, so B10 rescales it across the candidate list before weighting. The raw Jaccard stays in the B2 file.

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
Helpers: `src/lib/expression/de_contrast.py`, `src/lib/expression/de_select.py`

Scientific idea:
- A gene whose level changes in disease tissue versus healthy tissue is prioritized.
- Both directions count. The sign is kept in `log2_fold_change`.

Implementation (config `track_b.b4`):
1. Read the disease id already chosen in Step 1, and map the tissue onto a small group (`brain`, `liver`, `blood`).
2. Look up one saved contrast for that pair, in `config/default.yaml` or `data/external/de/pinned.json`. The subtype is not a separate file: it only matters when Step 1 selected a different disease id.
3. When nothing is saved, search Expression Atlas for human differential studies of that disease and tissue. Keep comparisons of disease versus healthy. Skip files that are not a gene / fold-change / p-value table, whatever their name. Rank the rest by how many genes change, and prefer a tissue study over a cell or organoid model. Save the winner and reuse it.
4. Score a measured gene from its fold change and p-value. Adjusted p is used when the file has it.
   - Not a real change (p above 0.05, or absolute log2 fold change below 0.5): score 0.
   - A real change: absolute log2 fold change / 2, capped at 1. A 4-fold change scores 1.
5. A gene absent from the table scores 0.5 (`not_measured`). A disease with no usable study scores 0.5 for every candidate (`no_contrast`). Zero means “measured and unchanged,” not “no file.”

Saved tables live in `data/external/de/`. See that folder’s `SOURCE.txt`.

Output:
- `stepB4_differential_expression.csv` (`differential_expression_score` is the B10 column)

---

## B5 — Pathway Enrichment / Relevance
Script: `src/stepB5_pathway.py`

Scientific idea:
- Candidates inside pathways that recur among known disease genes gain support.

Implementation:
1. Annotate seeds + candidates via mygene (**Reactome + KEGG** pathway IDs).
2. Count how many seeds carry each pathway (`seed_pathway_count`).
3. Keep **recurrent** pathways (seen in ≥2 seeds) as the disease pathway set
   (fallback to all seed pathways if too few).
4. For each candidate:
   - `candidate_pathway_count` — number of pathway IDs on the gene
   - `pathway_overlap_count` — overlap with the disease pathway set
   - `pathway_support_raw` — frequency-weighted overlap  
     (`sum(seed_count[p] for shared p) / n_seeds_with_pathways`)
   - `pathway_relevance_score` — min-max of `pathway_support_raw` (B10 contract)

This is a lightweight enrichment proxy: pathways shared by more seeds weigh more.
Full hypergeometric ORA (g:Profiler / Enrichr-style) remains a future upgrade.

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
4. B10 reads that score at weight 0.08. A candidate with no association stays at 0, so direct genetic evidence lifts a gene above an otherwise similar neighbor.

Output:
- `stepB6_genetic_support.csv`

Future upgrade:
- Direct GWAS/eQTL/mutation burden ingestion.

---

## B7 — Network Prioritization
Script: `src/stepB7_network_prioritization.py`

Scientific idea:
- A candidate inside the known-disease gene group is a stronger hypothesis than a gene hanging off one known gene.

Implementation:
1. Read B1 candidates and the real seed–candidate STRING links.
2. Ask STRING once for the other links among those genes (known–known and candidate–candidate), at the same score cutoff as B1.
3. Build that map. No synthetic hub.
4. For each candidate, average its direct STRING score to every known disease gene. A missing link counts as 0. This is `mean_link_strength`. Hop distance is still saved, but it is not the rank: at the usual cutoff many genes are one hop away, so hops stop separating them.
5. Bridge score: fraction of shortest paths between known disease genes that pass through the candidate. This stays 0 when the known genes are already linked to each other.
6. Combined, when the saved human STRING database is missing:
   - `network_prioritization_score = 0.75 * mean_link_strength + 0.25 * bridge`
7. When `data/external/string/9606.string.sqlite` is present, compare that attachment with about 100 ordinary proteins that have a similar partner count. `proximity_z` above 0 means the fit is stronger than those ordinary proteins. The rank uses that z-score in place of raw link strength: a typical protein of the same partner count scores 0.5, and a stronger fit scores higher without giving every clear fit the same number. A protein that touches almost everything drops unless this disease set is a special match.

Output:
- `stepB7_network_prioritization.csv`
  - `mean_distance_to_seeds`
  - `mean_link_strength`
  - `string_degree`
  - `proximity_z`
  - `betweenness`
  - `network_prioritization_score`

Build the background once: `python -m src.lib.track_b.string_background`

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
1. Merge outputs from B2, B3, B4, B5, B6, B7, B8, and B9.
2. Compute weighted final score using `track_b.final_ranking_weights`:
   - network support (B7)
   - pathway relevance (B5)
   - expression evidence (B4)
   - coexpression (B3)
   - functional similarity (B2)
   - genetic support (B6)
   - literature weak support (novelty, B8)
   - druggability (B9)
   - tissue relevance
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
- B4: differential expression (saved disease-vs-healthy contrast; neutral when none is pinned) ✅
- B5: pathway relevance (Reactome+KEGG, frequency-weighted) ✅
- B6: genetic support ✅
- B7: network prioritization ✅
- B8: novelty filter ✅
- B9: safety/druggability/structure (baseline now) ✅
- B10: final ranking ✅

This gives you a complete runnable Track B with clean architecture and inspectable artifacts, while keeping clear upgrade points for stronger omics/genetics integrations.
