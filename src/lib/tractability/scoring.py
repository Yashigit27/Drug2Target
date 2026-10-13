"""Map Open Targets flags (+ optional extras) into B9 sub-scores."""

from __future__ import annotations

from typing import Any


def _flag(flags: dict[str, bool], *keys: str) -> bool:
    for k in keys:
        if flags.get(k):
            return True
        # tolerate modality case variants already normalized in fetch_target_profile
    return False


def _lof_oe(genetic_constraint: list[dict[str, Any]]) -> float | None:
    for row in genetic_constraint or []:
        if str(row.get("constraintType") or "").lower() == "lof":
            try:
                return float(row.get("oe"))
            except (TypeError, ValueError):
                return None
    return None


def scores_from_ot_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """
    Build structure / druggability / safety components from an OT profile dict
    (as returned by fetch_target_profile).
    """
    flags = profile.get("tractability_flags") or {}

    # --- structure (OT only; PDBe may raise later) ---
    structure_bits = [
        _flag(flags, "sm:structure_with_ligand"),
        _flag(flags, "sm:high-quality_pocket"),
    ]
    structure = 0.35
    if structure_bits[0]:
        structure = 0.85
    elif structure_bits[1]:
        structure = 0.65

    # --- druggability ---
    drug_parts: list[float] = []
    if _flag(flags, "sm:approved_drug", "oc:approved_drug"):
        drug_parts.append(1.0)
    if _flag(flags, "sm:advanced_clinical", "pr:advanced_clinical", "ab:advanced_clinical"):
        drug_parts.append(0.85)
    if _flag(flags, "sm:high-quality_ligand", "pr:small_molecule_binder"):
        drug_parts.append(0.8)
    if _flag(flags, "sm:druggable_family"):
        drug_parts.append(0.7)
    if _flag(flags, "sm:high-quality_pocket"):
        drug_parts.append(0.65)
    # Antibody / PROTAC modality footholds
    if any(k.startswith("ab:") and v for k, v in flags.items()):
        drug_parts.append(0.55)
    if any(k.startswith("pr:") and v for k, v in flags.items()):
        drug_parts.append(0.55)

    probe_n = int(profile.get("chemical_probe_count") or 0)
    if probe_n > 0:
        drug_parts.append(min(0.9, 0.5 + 0.1 * min(probe_n, 4)))

    druggability = max(drug_parts) if drug_parts else 0.35

    # --- safety (conservative; liabilities / essentiality lower the score) ---
    safety = 0.55
    safety_n = int(profile.get("safety_liability_count") or 0)
    if safety_n >= 20:
        safety -= 0.20
    elif safety_n >= 5:
        safety -= 0.12
    elif safety_n >= 1:
        safety -= 0.06

    if profile.get("is_essential") is True:
        safety -= 0.15

    lof_oe = _lof_oe(profile.get("genetic_constraint") or [])
    # Low oe = more LoF-intolerant → riskier to inhibit
    if lof_oe is not None:
        if lof_oe < 0.35:
            safety -= 0.12
        elif lof_oe < 0.60:
            safety -= 0.06

    safety = max(0.15, min(0.95, safety))
    structure = max(0.15, min(0.95, structure))
    druggability = max(0.15, min(0.95, druggability))

    return {
        "structure_availability_score": round(structure, 4),
        "druggability_score": round(druggability, 4),
        "safety_score": round(safety, 4),
        "ot_approved_drug_flag": int(
            _flag(flags, "sm:approved_drug", "oc:approved_drug")
        ),
        "ot_structure_with_ligand_flag": int(_flag(flags, "sm:structure_with_ligand")),
        "chemical_probe_count": probe_n,
        "safety_liability_count": safety_n,
        "is_essential": profile.get("is_essential"),
        "lof_oe": lof_oe,
    }


def combine_readiness(
    structure: float,
    druggability: float,
    safety: float,
    *,
    w_struct: float = 0.4,
    w_drug: float = 0.4,
    w_safety: float = 0.2,
) -> float:
    total = max(1e-9, w_struct + w_drug + w_safety)
    return round(
        (w_struct * structure + w_drug * druggability + w_safety * safety) / total,
        4,
    )
