from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RunInput(BaseModel):
    """User-facing inputs for a run (human-only project)."""

    disease_label: str = Field(..., min_length=2, description="Primary disease name or phrase")
    disease_subtype: str | None = Field(
        default=None,
        description="Optional refinement (e.g. early-onset, familial). Used to steer ontology search.",
    )
    tissue: str | None = Field(
        default=None,
        description="Tissue / anatomical context (free text or Uberon-style label). Stored for downstream filtering.",
    )
    species: Literal["human"] = "human"


class DiseaseHit(BaseModel):
    id: str
    name: str
    entity: str = "disease"
    description: str | None = None


class DiseaseResolution(BaseModel):
    """Result of mapping the user's disease text to an Open Targets disease id."""

    query_used: str
    candidates: list[DiseaseHit]
    selected: DiseaseHit
    ambiguous: bool = False
    note: str | None = None


class Manifest(BaseModel):
    run_id: str
    pipeline_version: str
    input: RunInput
    disease_resolution: DiseaseResolution
    created_at: str
