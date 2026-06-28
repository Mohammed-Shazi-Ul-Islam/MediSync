import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

from app.models.intake import ReportStatus, SeverityHint


# ── Request Schemas ────────────────────────────────────────────────────────────

class SymptomReportCreate(BaseModel):
    """
    Accepts both modes:
    - Free-text only:  { "raw_text": "chest pain since 2 hours" }
    - Structured JSON: { "raw_text": "...", "structured_symptoms": { "pain": "chest", ... } }
    The AI engine (Module 02) will process raw_text regardless.
    structured_symptoms is optional enrichment from smart clients / forms.
    """
    raw_text: str
    structured_symptoms: dict | None = None
    severity_hint: SeverityHint = SeverityHint.MILD
    duration: str | None = None

    @field_validator("raw_text")
    @classmethod
    def validate_raw_text(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError(
                "Symptom description is too short. Please describe your symptoms in at least 10 characters."
            )
        if len(v) > 5000:
            raise ValueError("Symptom description cannot exceed 5000 characters")
        return v

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: str | None) -> str | None:
        if v is not None:
            v = v.strip()
            if len(v) > 255:
                raise ValueError("Duration description is too long (max 255 chars)")
        return v


# ── Response Schemas ───────────────────────────────────────────────────────────

class SymptomReportResponse(BaseModel):
    """
    Full report response — status field allows client to poll progress:
      pending → processing → triaged → closed
    urgency_level and specialist_recommendation are null until Module 02 runs.
    """
    id: uuid.UUID
    patient_id: uuid.UUID
    raw_text: str
    structured_symptoms: dict | None
    severity_hint: SeverityHint
    duration: str | None
    status: ReportStatus
    celery_task_id: str | None
    urgency_level: str | None
    specialist_recommendation: str | None
    ai_analysis: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SymptomReportList(BaseModel):
    """Paginated list response."""
    total: int
    page: int
    limit: int
    reports: list[SymptomReportResponse]
