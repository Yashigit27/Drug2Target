from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


class OpenTargetsSearchConfig(BaseModel):
    entity: str = "disease"
    max_hits: int = 15


class OpenTargetsAssociationsConfig(BaseModel):
    page_size: int = 500
    max_rows: int | None = 8000


class OpenTargetsConfig(BaseModel):
    graphql_url: str = "https://api.platform.opentargets.org/api/v4/graphql"
    search: OpenTargetsSearchConfig = Field(default_factory=OpenTargetsSearchConfig)
    associations: OpenTargetsAssociationsConfig = Field(
        default_factory=OpenTargetsAssociationsConfig
    )


class PathsConfig(BaseModel):
    storage_dir: str = "storage"
    outputs_dir: str = "outputs"
    data_raw_dir: str = "data/raw"
    registry_db: str = "storage/registry/d2t_registry.db"


class LiteratureRagConfig(BaseModel):
    enabled: bool = True
    first_pdate_years_back: int = 3
    max_articles: int = 40
    page_size: int = 20
    chunks_per_abstract_max: int = 12
    chunk_max_chars: int = 450
    top_chunks_global: int = 80
    max_genes_per_run: int = 500
    retrieval_query: str = (
        "therapeutic target gene protein pathway drug biomarker novel candidate"
    )


class TrackAConfig(BaseModel):
    enabled: bool = True
    top_n_for_analysis: int = 120
    # Step A1 saturation (crowdedness) weights
    crowdedness_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "publication_count": 0.45,
            "approved_drug_flag": 0.25,
            "clinical_flag": 0.2,
            "ligand_flag": 0.1,
        }
    )
    # Step A5 final ranking weights
    final_ranking_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "biological_relevance": 0.35,
            "cadd_readiness": 0.25,
            "tissue_relevance": 0.20,
            "low_crowdedness": 0.20,
        }
    )
    # Step A2 thresholds
    crowded_high_quantile: float = 0.8
    crowded_extreme_quantile: float = 0.95


class B3CoexpressionConfig(BaseModel):
    """Track B step B3 — tissue expression / coexpression proxy providers."""

    # string_proxy | gtex_tissue | hybrid
    provider: str = "hybrid"
    gtex_median_path: str = "data/external/gtex/gene_median_tpm.gct.gz"
    expression_weight: float = 0.7
    string_proxy_weight: float = 0.3
    default_tissue: str = "brain"
    tissue_map: dict[str, str] = Field(
        default_factory=lambda: {
            "brain": "Brain_Cortex",
            "cortex": "Brain_Cortex",
            "liver": "Liver",
            "hepatic": "Liver",
            "blood": "Whole_Blood",
            "lung": "Lung",
            "heart": "Heart_Left_Ventricle",
            "kidney": "Kidney_Cortex",
            "muscle": "Muscle_Skeletal",
            "skin": "Skin_Sun_Exposed_Lower_leg",
            "pancreas": "Pancreas",
            "adipose": "Adipose_Subcutaneous",
            "colon": "Colon_Transverse",
            "stomach": "Stomach",
            "thyroid": "Thyroid",
            "nerve": "Nerve_Tibial",
            "spleen": "Spleen",
            "pituitary": "Pituitary",
        }
    )


class B9TractabilityConfig(BaseModel):
    """Track B step B9 — structure / druggability / safety readiness."""

    # defaults | ot_tractability | hybrid (OT + optional PDBe)
    provider: str = "hybrid"
    use_pdbe: bool = True
    structure_weight: float = 0.4
    druggability_weight: float = 0.4
    safety_weight: float = 0.2
    # Max candidates to query (same ballpark as B1 top list)
    max_genes: int = 200


class TrackBConfig(BaseModel):
    enabled: bool = True
    seed_top_n: int = 60
    string_required_score: int = 400
    string_partners_per_seed: int = 40
    top_candidates_for_scoring: int = 180
    final_ranking_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "network_support": 0.22,
            "pathway_relevance": 0.18,
            "expression_evidence": 0.18,
            "coexpression": 0.13,
            "literature_weak_support": 0.09,
            "druggability": 0.10,
            "tissue_relevance": 0.10,
        }
    )
    b3: B3CoexpressionConfig = Field(default_factory=B3CoexpressionConfig)
    b9: B9TractabilityConfig = Field(default_factory=B9TractabilityConfig)


class TissueFilterConfig(BaseModel):
    enabled: bool = True
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "snippet": 0.35,
            "literature": 0.40,
            "mygene": 0.25,
        }
    )
    max_genes_for_epmc: int = 80


class FusionConfig(BaseModel):
    enabled: bool = True
    tier1_track_threshold: float = 0.65
    tier1_tissue_threshold: float = 0.70
    tier1_cadd_threshold: float = 0.60
    tier2_track_threshold: float = 0.40
    portfolio_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "track_a": 0.35,
            "track_b": 0.35,
            "tissue": 0.15,
            "cadd": 0.15,
        }
    )


class LLMConfig(BaseModel):
    enabled: bool = True
    provider: str = "openai"
    model: str = "gpt-4o-mini"
    api_key_env: str = "OPENAI_API_KEY"
    base_url_env: str = "OPENAI_BASE_URL"
    max_tokens: int = 700


class AppConfig(BaseModel):
    species: str = "human"
    open_targets: OpenTargetsConfig = Field(default_factory=OpenTargetsConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    literature_rag: LiteratureRagConfig = Field(default_factory=LiteratureRagConfig)
    track_a: TrackAConfig = Field(default_factory=TrackAConfig)
    track_b: TrackBConfig = Field(default_factory=TrackBConfig)
    tissue_filter: TissueFilterConfig = Field(default_factory=TissueFilterConfig)
    fusion: FusionConfig = Field(default_factory=FusionConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)


@lru_cache(maxsize=1)
def load_config() -> AppConfig:
    load_dotenv()
    root = _repo_root()
    cfg_path = root / "config" / "default.yaml"
    data: dict[str, Any] = {}
    if cfg_path.is_file():
        with cfg_path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    if os.environ.get("LITERATURE_RAG_ENABLED", "").lower() in ("0", "false", "no"):
        data.setdefault("literature_rag", {})["enabled"] = False
    ot = data.get("open_targets", {})
    if url := os.environ.get("OPENTARGETS_GRAPHQL_URL"):
        ot = {**ot, "graphql_url": url}
        data["open_targets"] = ot
    return AppConfig.model_validate(data)
