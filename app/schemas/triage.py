"""
app/schemas/triage.py

Pydantic models for Module 02 AI Triage Engine output.

TriageResult is the structured object produced by the LangChain pipeline.
It is:
  - Used by PydanticOutputParser to coerce raw LLM JSON into typed Python
  - Serialised to dict and stored in symptom_reports.ai_analysis (JSONB)
  - Its fields are also written to urgency_level + specialist_recommendation columns

Design notes:
  - All fields are kept optional where the LLM might not have enough information
    (e.g. a vague "I feel bad" report may not yield extracted symptoms)
  - confidence is a float the LLM self-reports — not a hard guarantee
  - red_flags are raw text phrases the LLM identified as alarming signals
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ExtractedSymptom(BaseModel):
    """
    A single structured symptom extracted from the patient's free-text report.

    Examples:
        {"name": "chest pain", "body_part": "chest", "severity": "severe", "onset": "sudden"}
        {"name": "nausea", "body_part": null, "severity": "mild", "onset": "gradual"}
    """

    name: str = Field(description="Canonical symptom name, e.g. 'chest pain', 'dyspnea'")
    body_part: str | None = Field(
        default=None,
        description="Anatomical location if mentioned, e.g. 'left arm', 'lower abdomen'",
    )
    severity: Literal["mild", "moderate", "severe"] | None = Field(
        default=None,
        description="Symptom severity inferred from patient description",
    )
    onset: Literal["sudden", "gradual", "unknown"] | None = Field(
        default=None,
        description="How quickly the symptom started",
    )
    duration: str | None = Field(
        default=None,
        description="How long the symptom has been present, e.g. '2 hours', '3 days'",
    )


class TriageResult(BaseModel):
    """
    Full structured output from the AI triage pipeline.

    Stored in symptom_reports.ai_analysis as JSONB.
    Top-level fields (urgency_level, specialist_recommendation) are also
    denormalised into their own columns for fast filtering.
    """

    urgency_level: Literal["critical", "moderate", "routine"] = Field(
        description=(
            "Overall triage classification. "
            "critical = needs emergency care immediately; "
            "moderate = needs doctor within hours; "
            "routine = can wait for a scheduled appointment"
        )
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model's self-assessed confidence in the urgency classification (0.0–1.0)",
    )
    reasoning: str = Field(
        description="One or two sentence explanation of why this urgency level was assigned",
    )
    specialist_recommendation: str = Field(
        description=(
            "Type of specialist most appropriate for this presentation, "
            "e.g. 'cardiologist', 'neurologist', 'general_practitioner', 'emergency_medicine'"
        )
    )
    extracted_symptoms: list[ExtractedSymptom] = Field(
        default_factory=list,
        description="List of structured symptoms extracted from the patient's free-text",
    )
    red_flags: list[str] = Field(
        default_factory=list,
        description="Alarming phrases or signs identified in the report, e.g. ['chest pain', 'diaphoresis']",
    )
    relevant_conditions: list[str] = Field(
        default_factory=list,
        description="Possible medical conditions retrieved from the knowledge base (differential context)",
    )
