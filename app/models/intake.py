from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.case_assignment import CaseAssignment


class SeverityHint(str, enum.Enum):
    """Self-reported severity from the patient at intake time."""
    MILD = "mild"
    MODERATE = "moderate"
    SEVERE = "severe"


class ReportStatus(str, enum.Enum):
    """
    Lifecycle of a symptom report through the MediSync pipeline.

    PENDING    → Just created, waiting to be picked up by Celery
    PROCESSING → Celery worker has started the AI triage task
    TRIAGED    → AI has classified urgency + recommended specialist (Module 02)
    CLOSED     → Doctor has reviewed and closed the case (Module 05)
    """
    PENDING = "pending"
    PROCESSING = "processing"
    TRIAGED = "triaged"
    CLOSED = "closed"


class SymptomReport(Base):
    """
    Core intake record. Every patient submission creates one SymptomReport.

    Key design decisions:
    - raw_text: stores the original free-text exactly as typed — never mutated
    - structured_symptoms: JSONB allows flexible, queryable schema-less data
      (a headache report has different fields than a chest pain report)
    - ai_analysis: JSONB populated by Module 02 — will hold urgency, extracted
      symptoms, confidence scores, reasoning trace etc.
    - celery_task_id: allows the client to poll task status independently
    """
    __tablename__ = "symptom_reports"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Symptom Data ───────────────────────────────────────────────────────────
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_symptoms: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    severity_hint: Mapped[SeverityHint] = mapped_column(
        SAEnum(SeverityHint, name="severityhint"),
        default=SeverityHint.MILD,
        nullable=False,
    )
    duration: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Pipeline State ─────────────────────────────────────────────────────────
    status: Mapped[ReportStatus] = mapped_column(
        SAEnum(ReportStatus, name="reportstatus"),
        default=ReportStatus.PENDING,
        nullable=False,
        index=True,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── AI Results (populated by Module 02) ───────────────────────────────────
    urgency_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    specialist_recommendation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Routing Results (populated by Module 03) ─────────────────────────────
    routing_decision: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Module 03: Full RoutingDecision JSON (specialist, confidence, method, reasoning, etc.)",
    )

    # ── Assignment (populated by Module 04) ──────────────────────────────────
    assigned_doctor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Module 04: Denormalised FK to the currently active doctor assignment.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    patient: Mapped[Patient] = relationship("Patient", back_populates="symptom_reports")
    case_assignments: Mapped[list[CaseAssignment]] = relationship(
        "CaseAssignment",
        back_populates="report",
        cascade="all, delete-orphan",
    )
