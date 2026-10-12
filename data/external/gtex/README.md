# GTEx median TPM for Track B step B3

B3 scores candidate genes by **tissue expression** using GTEx median TPM.

## Download (once)

1. Open: https://gtexportal.org/home/downloads/adult-gtex/bulk_tissue_expression  
2. Download the open-access file named like:  
   `GTEx_Analysis_*_gene_median_tpm.gct.gz` (~5–10 MB)  
3. Place it here as either:
   - `gene_median_tpm.gct.gz` (recommended), or  
   - keep the original filename — B3 also accepts any `*gene_median_tpm*.gct.gz` in this folder.

## Behavior

| Situation | What B3 does |
|-----------|----------------|
| File present + tissue mapped | Use GTEx (hybrid with STRING by default) |
| File missing | Fall back to STRING neighborhood proxy |
| Gene missing in GTEx | STRING fallback for that gene only |

Config: `config/default.yaml` → `track_b.b3`

Do **not** commit the large GTEx `.gct.gz` to git (ignored).
