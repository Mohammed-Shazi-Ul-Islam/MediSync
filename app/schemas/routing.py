"""
app/schemas/routing.py

Module 03 — Specialist Router: Pydantic models.

RoutingDecision is the enriched output produced by the HybridSpecialistRouter.
It captures:
  - The final specialist recommendation (enum-validated)
  - How confident the system is (0.0–1.0)
  - Whether the rule layer, semantic layer, or both contributed
  - A human-readable reasoning chain for audit / explainability
  - Alternative specialists for the doctor dashboard to consider
  - An emergency override flag that forces ER routing regardless of scores

RoutingRequest is the request body accepted by POST /api/v1/routing/decide.
It accepts either a TriageResult payload directly *or* a report_id to look up
an already-stored result — whichever the caller finds convenient.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.triage import TriageResult


# ── Specialist Enum ────────────────────────────────────────────────────────────

class SpecialistType(str, Enum):
    """
    Canonical specialist type codes used throughout the routing layer.

    These map 1-to-1 with specialist_display_names and the specialist rulebook.
    New specialist types should be added here AND in specialist_kb.py.
    """
    EMERGENCY_MEDICINE    = "emergency_medicine"
    CARDIOLOGIST          = "cardiologist"
    NEUROLOGIST           = "neurologist"
    NEUROSURGEON          = "neurosurgeon"
    PULMONOLOGIST         = "pulmonologist"
    GASTROENTEROLOGIST    = "gastroenterologist"
    GENERAL_SURGEON       = "general_surgeon"
    ENDOCRINOLOGIST       = "endocrinologist"
    UROLOGIST             = "urologist"
    VASCULAR_SURGEON      = "vascular_surgeon"
    PSYCHIATRIST          = "psychiatrist"
    GENERAL_PRACTITIONER  = "general_practitioner"
    ORTHOPEDIST           = "orthopedist"
    RHEUMATOLOGIST        = "rheumatologist"
    DERMATOLOGIST         = "dermatologist"


# ── Display Names ──────────────────────────────────────────────────────────────

SPECIALIST_DISPLAY_NAMES: dict[str, str] = {
    "emergency_medicine":   "Emergency Medicine Physician",
    "cardiologist":         "Cardiologist",
    "neurologist":          "Neurologist",
    "neurosurgeon":         "Neurosurgeon",
    "pulmonologist":        "Pulmonologist",
    "gastroenterologist":   "Gastroenterologist",
    "general_surgeon":      "General Surgeon",
    "endocrinologist":      "Endocrinologist",
    "urologist":            "Urologist",
    "vascular_surgeon":     "Vascular Surgeon",
    "psychiatrist":         "Psychiatrist",
    "general_practitioner": "General Practitioner",
    "orthopedist":          "Orthopaedic Surgeon",
    "rheumatologist":       "Rheumatologist",
    "dermatologist":        "Dermatologist",
}

SPECIALIST_DESCRIPTIONS: dict[str, str] = {
    "emergency_medicine":   "Handles immediately life-threatening conditions; ER / emergency department",
    "cardiologist":         "Heart and vascular system diseases; arrhythmias, heart failure, angina",
    "neurologist":          "Disorders of the brain, spinal cord, and nerves; stroke, migraine, epilepsy",
    "neurosurgeon":         "Surgical intervention for CNS conditions; tumours, disc herniation, cauda equina",
    "pulmonologist":        "Lung and respiratory system diseases; COPD, asthma (follow-up), ILD",
    "gastroenterologist":   "Digestive system disorders; pancreatitis, IBD, GI bleeding, liver disease",
    "general_surgeon":      "Surgical abdominal conditions; appendicitis, cholecystitis, bowel obstruction",
    "endocrinologist":      "Hormone and metabolic disorders; diabetes, thyroid, adrenal conditions",
    "urologist":            "Urinary tract and male reproductive system; renal colic, UTI, haematuria",
    "vascular_surgeon":     "Blood vessel diseases; DVT, AAA, peripheral vascular disease",
    "psychiatrist":         "Mental health and psychiatric conditions; panic disorder, depression, psychosis",
    "general_practitioner": "Primary care for routine and non-specialist presentations",
    "orthopedist":          "Bone, joint, and musculoskeletal conditions; fractures, arthritis, sports injuries",
    "rheumatologist":       "Autoimmune and inflammatory joint/soft-tissue conditions; RA, lupus, gout",
    "dermatologist":        "Skin, hair, and nail conditions; cellulitis, eczema, skin infections",
}


# ── Routing Decision ───────────────────────────────────────────────────────────

class RoutingDecision(BaseModel):
    """
    Full output from the HybridSpecialistRouter.

    Stored in symptom_reports.routing_decision as JSONB.
    Also returned directly from POST /api/v1/routing/decide.

    Fields:
      specialist              — The routed specialist type (enum code)
      specialist_display_name — Human-readable name for the specialist
      confidence              — Fused confidence 0.0–1.0
      routing_method          — Which layer(s) contributed to the decision
      rule_score              — Confidence contribution from the rule layer
      semantic_score          — Confidence contribution from the AI semantic layer
      reasoning               — Explanation of why this specialist was chosen
      alternative_specialists — Runner-up specialists (for dashboard display)
      escalate_to_emergency   — True when hard red-flag rules override routing
    """

    specialist: str = Field(
        description="Specialist type code, e.g. 'cardiologist'. One of SpecialistType values."
    )
    specialist_display_name: str = Field(
        description="Human-readable specialist name, e.g. 'Cardiologist'"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Fused routing confidence (0.0–1.0); higher means more certain",
    )
    routing_method: Literal["rule_only", "semantic_only", "hybrid", "emergency_override"] = Field(
        description=(
            "rule_only = rule engine fired with high confidence (≥ threshold); "
            "semantic_only = no rules matched, AI layer decided; "
            "hybrid = both layers contributed to the final score; "
            "emergency_override = critical red-flag forced emergency_medicine"
        )
    )
    rule_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from the deterministic rule layer (0 if not used)",
    )
    semantic_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score from the ChromaDB semantic layer (0 if not used)",
    )
    reasoning: str = Field(
        description="Human-readable explanation of the routing decision (1–3 sentences)"
    )
    alternative_specialists: list[str] = Field(
        default_factory=list,
        description="Runner-up specialist codes in case the primary is unavailable",
    )
    escalate_to_emergency: bool = Field(
        default=False,
        description=(
            "True when a hard red-flag rule overrides routing — "
            "the patient should go to an emergency department immediately"
        ),
    )


# ── Specialist Info (for GET /specialists) ────────────────────────────────────

class SpecialistInfo(BaseModel):
    """Summary record for one specialist type — used by GET /api/v1/routing/specialists."""
    code: str
    display_name: str
    description: str


# ── Request body for POST /api/v1/routing/decide ─────────────────────────────

class RoutingRequest(BaseModel):
    """
    Request body for the routing endpoint.

    Callers can supply EITHER:
      - triage_result: a full TriageResult payload (direct inline routing)
      - report_id:     UUID of a saved SymptomReport (router looks it up in DB)

    At least one must be provided; if both are given, triage_result takes precedence.
    """

    triage_result: TriageResult | None = Field(
        default=None,
        description="Inline TriageResult payload — use this for direct routing without DB lookup",
    )
    report_id: str | None = Field(
        default=None,
        description="UUID of an existing SymptomReport — router loads ai_analysis from DB",
    )

    @field_validator("report_id")
    @classmethod
    def at_least_one_field(cls, v: str | None, info) -> str | None:
        """Ensure at least one of triage_result / report_id is provided."""
        if v is None and info.data.get("triage_result") is None:
            raise ValueError("Provide either 'triage_result' or 'report_id' (or both).")
        return v
