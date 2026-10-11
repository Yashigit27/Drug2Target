# Pipeline logic — human disease → target discovery

This document is the **single source of truth** for *why* each step exists, *what* each script does at function level, *which* packages and external services are involved, and *how* pieces connect. It also records **design choices** and **alternative approaches** we considered.

---

## 0. Environment and project layout

### 0.1 What was set up

| Item | Purpose |
|------|---------|
| `requirements.txt` | Pinned-style ranges: `httpx`, `pandas`, `pydantic`, `PyYAML`, `python-dotenv`, `tqdm`, `scikit-learn` (TF‑IDF RAG retrieval), `mygene` (human symbol validation). |
| `.gitignore` | Ignores virtualenvs, caches, `.env`, and per-run output folders under `outputs/`. |
| `.env.example` | Documents optional env overrides (e.g. Open Targets GraphQL URL). |
| `config/default.yaml` | Central thresholds: Open Targets pagination, optional cap on association rows, directory names. |
| `src/` | Python package for steps and shared `lib/`. |
| `outputs/<run_id>/` | **Run folder**: `manifest.json`, `inputs.json`, `artifacts/*.csv`. |
| `data/raw/<run_id>/` | Cached raw API payloads (JSON) for audit and reprocessing. |

### 0.2 How to create the environment (recommended)

From the repository root (`d:\D2T`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -r requirements.txt
```

**Alternatives:**

- **Conda / Mamba:** create an env with Python 3.11+ and `pip install -r requirements.txt` inside it. Good if you later add RDKit or docking binaries.
- **uv:** `uv venv` then `uv pip install -r requirements.txt` — faster resolver, same outcome.

**What we chose:** plain `venv` + `pip` for minimal surprise on Windows.

### 0.3 How to run commands

All commands assume the **current working directory** is the repo root and the **Python 3.11+** interpreter has dependencies installed.

```powershell
python -m src.cli step1 --disease "Alzheimer disease" --tissue brain --subtype "late-onset"
python -m src.cli step2 --run-id "<paste-run-id>"
```

You can also invoke modules directly:

```powershell
python -m src.step01_input --disease "Alzheimer disease"
python -m src.step02_collect --run-id "<run-id>"
```

### 0.4 How modules connect (data spine)

1. **Step 1** creates `outputs/<run_id>/manifest.json` (full run state + ontology resolution) and `inputs.json` (copy of structured user input).
2. **Step 2** reads `manifest.json`, pulls **Open Targets** associations, optionally **literature RAG** (Europe PMC → TF‑IDF chunks → gene extraction → **mygene** validation), merges and dedupes, writes `artifacts/known_disease_genes.csv` plus raw JSON caches under `data/raw/<run_id>/`.

Later steps (PPI expansion, centrality, pathways, novelty, druggability) will **only read/write under the same `run_id` folder** so runs stay reproducible and parallelizable.

---

## 1. Configuration layer

### 1.1 `src/lib/settings.py`

| Function / element | Responsibility |
|--------------------|----------------|
| `load_config()` | Loads `config/default.yaml`, applies optional `.env` overrides (`OPENTARGETS_GRAPHQL_URL`, `LITERATURE_RAG_ENABLED`), returns a typed `AppConfig` (`pydantic`). |

**Techniques:** structured config validation; single cached load (`lru_cache`) so API clients read consistent settings.

**Packages:** `PyYAML`, `pydantic`, `python-dotenv`.

**Alternatives:** Hydra, OmegaConf, or TOML-only config — heavier; YAML + Pydantic is enough for a research pipeline.

---

## 2. Data models

### 2.1 `src/lib/models.py`

| Model | Fields / meaning |
|-------|-------------------|
| `RunInput` | `disease_label`, optional `disease_subtype`, optional `tissue`, `species` (literal `"human"` only). |
| `DiseaseHit` | Ontology hit: `id` (e.g. `MONDO_0004975`), `name`, `entity`, optional `description`. |
| `DiseaseResolution` | `query_used`, `candidates[]`, `selected`, `ambiguous` flag, optional `note`. |
| `Manifest` | `run_id`, `pipeline_version`, `input`, `disease_resolution`, ISO `created_at`. |

**Why Pydantic:** JSON-serializable manifests with validation at the edges (CLI / future MCP).

---

## 3. Paths and manifest I/O

### 3.1 `src/lib/paths.py`

| Function | Responsibility |
|----------|------------------|
| `repo_root()` | Absolute path to repository root. |
| `outputs_dir()`, `run_dir(run_id)`, `ensure_run_dir(run_id)` | Filesystem layout for runs. |
| `manifest_path`, `inputs_path` | Standard locations. |
| `data_raw_dir()` | Shared cache root for API JSON. |

### 3.2 `src/lib/run_manifest.py`

| Function | Responsibility |
|----------|------------------|
| `write_manifest(path, Manifest)` | Pretty JSON for human diffing. |
| `read_manifest(path)` | Parse back into `Manifest`. |

---

## 4. Step 1 — disease / subtype / tissue input (human-only)

### 4.1 Script: `src/step01_input.py`

**Goal:** Turn a natural-language disease description plus optional subtype and tissue into a **single resolved Open Targets disease identifier**, and mint a **`run_id`**.

| Function | What it does | Techniques |
|----------|----------------|------------|
| `_select_candidate(...)` | Chooses `selected` disease from search hits: subtype keyword match in name/description, else exact name match, else first hit. | Heuristic ranking (simple rules). |
| Search string | Uses **`disease_label` only** for Open Targets `search` (subtype is **not** concatenated into the query string) to avoid noisy unrelated ontology hits; subtype is used only for **selection** among returned candidates. | |
| `run_step1(inp, disease_id_override, run_id)` | Validates `species == human`, resolves disease (search or explicit id), writes `manifest.json` + `inputs.json`. | UUID run id; `httpx` client reuse. |
| `main()` | `argparse` CLI wrapper. | |

**External service:** Open Targets Platform GraphQL (`search` + optional `disease` header).

**Packages:** `httpx`, `pydantic`, stdlib `uuid`, `datetime`.

**Outputs:**

- `outputs/<run_id>/manifest.json` — includes full **candidate list** for transparency.
- `outputs/<run_id>/inputs.json` — quick view of user input.

**Alternatives considered:**

- **Force user to always pass a MONDO/EFO id:** maximum precision, worse UX — we support `--disease-id` as an override instead.
- **Use OLS / MONDO search only:** good for ontology browsing; Open Targets search already returns MONDO/EFO ids integrated with their association graph — **we chose Open Targets** for one-hop alignment with Step 2.
- **Embedding / LLM disease normalization:** powerful but non-deterministic — defer to optional future RAG; core pipeline stays API-grounded.

**Tissue field:** stored in `RunInput` for **downstream** use (e.g. expression filter, pathway context). Step 1 does **not** yet filter targets by tissue.

---

## 5. Step 2 — Open Targets + literature RAG → merged targets

### 5.1 Script: `src/step02_collect.py`

**Goal:** Build one **combined** table: Open Targets disease–gene evidence **plus** literature-derived human gene candidates from **recent abstracts**, then **merge / dedupe**.

**Pipeline inside `run_step2`:**

1. Read `manifest.json`.
2. **Open Targets:** paginate `associatedTargets`, map to a dataframe, dedupe by Ensembl id (max association score).
3. **Literature RAG** (if enabled in `config/default.yaml` and not `--skip-literature` / `LITERATURE_RAG_ENABLED`):
   - Build Europe PMC query from the user’s **`disease_label`** (broader recall than the ontology display name alone).
   - Fetch recent articles (`FIRST_PDATE` window = `literature_rag.first_pdate_years_back`).
   - Chunk title+abstract; **TF‑IDF** rank chunks against `literature_rag.retrieval_query` (retrieval step of RAG — no LLM).
   - Extract ALLCAPS-like tokens; **validate human gene symbols** via **mygene**; aggregate PMIDs + max chunk score + snippet.
4. **Merge** (`gene_merge.py`): OT rows get `source=open_targets`; overlapping literature updates to `open_targets+literature_rag`; literature-only rows get `source=literature_rag`.
5. **Dedupe** by Ensembl id when present, else by `gene_symbol` key.
6. Write `artifacts/known_disease_genes.csv`.

| Function | Responsibility |
|----------|----------------|
| `associations_to_dataframe(...)` | OT rows → columns used by merge. |
| `run_step2(run_id, skip_literature=...)` | Orchestrates OT + optional RAG + merge. |

**CLI:** `python -m src.cli step2 --run-id ...` or `--skip-literature` for OT-only.

### 5.2 `src/lib/europepmc_client.py`

| Function | Responsibility |
|----------|----------------|
| `build_disease_literature_query(...)` | Europe PMC query string: `ABSTRACT:"…" AND (gene OR target OR …) AND FIRST_PDATE:[…]`. |
| `search_articles(...)` | Cursor-paginated search; returns title/abstract/pmid/year. |

### 5.3 `src/lib/rag_retrieval.py`

| Function | Responsibility |
|----------|----------------|
| `chunk_abstract(...)` | Sentence-ish chunks for retrieval. |
| `tfidf_top_chunks(...)` | **TF‑IDF + cosine similarity** — lightweight “embedding-free” RAG retrieval on CPU. |

**Alternatives:** sentence-transformers + FAISS/Chroma (heavier, GPU-friendly at scale); LLM-only extraction without retrieval (high hallucination risk on gene lists).

### 5.4 `src/lib/literature_genes.py`

| Function | Responsibility |
|----------|----------------|
| `extract_gene_like_symbols` | Regex candidates; stoplist for common acronyms. |
| `validate_symbols_human` | **mygene** batch lookup (`scopes=symbol`, `species=human`). |
| `aggregate_literature_evidence` | Per validated symbol: max RAG score, merged PMIDs, snippet. |

### 5.5 `src/lib/literature_rag_run.py`

| Function | Responsibility |
|----------|----------------|
| `run_literature_rag(manifest)` | Wires EPMC → chunks → TF‑IDF → symbols → mygene → rows + summary dict for JSON cache. |

### 5.6 `src/lib/gene_merge.py`

| Function | Responsibility |
|----------|----------------|
| `merge_opentargets_and_literature(...)` | Union / join evidence; `_dedup` key prefers Ensembl. |

### 5.7 Client: `src/lib/opentargets_client.py`

(Same as before: GraphQL, pagination, `cache_raw_json`.)

**Important API detail:** the GraphQL field is `disease(efoId: ...)`, but the **id may be MONDO or EFO** — Open Targets accepts both for this argument.

**Outputs:**

- `outputs/<run_id>/artifacts/known_disease_genes.csv` — **combined**; columns include `source`, `association_score`, `literature_max_rag_score`, `literature_pmids`, `literature_snippet`.
- `data/raw/<run_id>/open_targets_associations_raw.json`
- `data/raw/<run_id>/literature_rag_summary.json` — counts + Europe PMC query string used.

**Alternatives for extra databases (roadmap):** DisGeNET, GWAS Catalog (separate evidence columns), user seed CSV — merge with explicit `source` tags.

**Config cap:** Open Targets `max_rows` still applies; literature uses `literature_rag.max_articles`, `top_chunks_global`, `max_genes_per_run`.

---

## 6. CLI orchestration

### 6.1 `src/cli.py`

| Piece | Responsibility |
|-------|----------------|
| `build_parser()` | `argparse` subcommands `step1`, `step2` (`step2` supports `--skip-literature`). |
| `main()` | Dispatches to `run_step1` / `run_step2`. |

**Alternatives:** Typer or Click — nicer DX; `argparse` avoids extra dependencies.

---

## 7. MCP (Model Context Protocol) — agent context **best practices** (for when you wire it in)

MCP is still optional; the **science stays in Python**. When you expose this pipeline to an agent, use this pattern:

### 7.1 Tools = side effects + structured facts

| MCP tool (suggested) | Calls | Returns (ideal) |
|---------------------|--------|-----------------|
| `pipeline_step1` | `run_step1` | `{ run_id, manifest_path, selected_disease_id }` |
| `pipeline_step2` | `run_step2` | `{ csv_path, row_count, literature_summary_path? }` |
| `get_run_manifest` | read `manifest.json` | Full JSON or a **stable schema** subset |
| `get_combined_genes` | read `known_disease_genes.csv` | Parsed rows or file URI |

**Do not** implement “extract genes” only inside the LLM: Step 2 already returns **CSV + PMIDs + scores** — the agent should **cite those tool outputs**, not invent symbols.

### 7.2 Resources = files the model can read without re-running

Register **resources** (or return paths) such as:

- `outputs/<run_id>/manifest.json`
- `outputs/<run_id>/artifacts/known_disease_genes.csv`
- `data/raw/<run_id>/literature_rag_summary.json`

So **MCP “context”** = *paths + hashes + row counts* from tools, not a wall of pasted abstracts.

### 7.3 RAG and agents

- **Pipeline RAG** (this repo): retrieval = **Europe PMC + TF‑IDF chunks**; “generation” = **mygene validation** + merge — **deterministic** where possible.
- **Agent RAG** (optional later): if you add an LLM to *summarize* literature, keep it **downstream** of the CSV, and require **PMID citations** from `literature_pmids`.

### 7.4 Safety / grounding rules for MCP hosts

- Return **PMIDs** and **Open Targets ids** as structured fields.
- Prefer **one `run_id` per session** so the agent does not mix diseases.
- If the model proposes new targets not in `known_disease_genes.csv`, treat that as **hypothesis**, not pipeline output.

**Alternatives:** FastAPI microservice instead of MCP — more overhead; MCP fits Cursor/agents well when tools map 1:1 to your functions.

---

## 8. End user flows

| User type | Flow |
|-----------|------|
| You (CLI) | `step1` → note `run_id` → `step2` → open CSV in `artifacts/`. |
| Future UI / agent | Same functions; MCP or HTTP wrapper. |

---

## 9. Changelog of design decisions (this milestone)

1. **Human-only** enforced in `RunInput.species` literal type and a runtime check in Step 1.
2. **Open Targets GraphQL** as first external integration (search + associations) — verified against live API (`disease(efoId: ...)`).
3. **Run-scoped directories** under `outputs/<run_id>` plus **raw JSON cache** under `data/raw/<run_id>` for provenance.
4. **Dedup** associations by `ensembl_gene_id` keeping the **maximum** `association_score`.
5. **Configurable row cap** (`max_rows`) to balance completeness vs runtime for large diseases.
6. **Literature “RAG”** without LLMs: Europe PMC → chunk → **TF‑IDF retrieval** → regex candidates → **mygene** human validation → merge with OT; literature query uses **`input.disease_label`** first for abstract recall, with fallback to the resolved ontology name if needed.

---

## 10. Separator template for future steps

When you add Step 3+, append a new section per script using this pattern:

```
--------------------------------------------------------------------------------
## Step N — <short title>
### N.1 Script: `src/step0N_....py`
| Function | Input | Output | Techniques | Packages |
--------------------------------------------------------------------------------
```

This keeps the document mechanically easy to extend.
