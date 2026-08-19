"""
app/models/case_assignment.py

Module 04 + 05 — Core join table between SymptomReport and Doctor.

Lifecycle:  offered → accepted | rejected | expired

Why a separate table instead of a FK on symptom_reports?
  A single report may be offered to multiple doctors sequentially (escalation chain).
  symptom_reports.assigned_doctor_id is a denormalised shortcut pointing to the
  *current* active assignment's doctor — updated whenever a new assignment is created.

  The full history of which doctors were offered/rejected is captured here, which
  gives the analytics layer a complete audit trail.

Escalation logic (Module 04):
  - When a CaseAssignment expires (doctor didn't respond in N minutes), its status
    is set to 'expired' and escalation_count is incremented.
  - A new CaseAssignment is created for the next available doctor.
  - doctor_notes is used both by doctors (rejection reason) and by the system
    (escalation audit message).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.doctor import Doctor
    from app.models.intake import SymptomReport


class AssignmentStatus(str, enum.Enum):
    """
    State machine for a single case assignment offer.

    OFFERED  → Doctor was alerted; waiting for response.
    ACCEPTED → Doctor accepted the case; they now own it.
    REJECTED → Doctor explicitly rejected; triggers immediate escalation.
    EXPIRED  → Doctor did not respond within escalation_minutes; auto-expired.
    """
    OFFERED  = "offered"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED  = "expired"


class CaseAssignment(Base):
    """
    One row per doctor-offer for a given SymptomReport.

    A report can have multiple rows here (one per escalation step).
    Only one should have status=ACCEPTED at any point in time.
    """

    __tablename__ = "case_assignments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    # ── FK Links ───────────────────────────────────────────────────────────────
    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("symptom_reports.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── State ──────────────────────────────────────────────────────────────────
    status: Mapped[AssignmentStatus] = mapped_column(
        SAEnum(AssignmentStatus, name="assignmentstatus"),
        default=AssignmentStatus.OFFERED,
        nullable=False,
        index=True,
    )

    # ── Timestamps ─────────────────────────────────────────────────────────────
    offered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Set when doctor accepts or rejects.",
    )

    # ── Escalation Metadata ────────────────────────────────────────────────────
    escalation_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        comment="0 = first offer, 1 = first escalation, etc.",
    )
    celery_escalation_task_id: Mapped[str | None] = mapped_column(
        # Stored so we can revoke the escalation Celery task if the doctor accepts
        # before the countdown fires. Module 04.
        __import__("sqlalchemy").String(255),
        nullable=True,
        comment="Celery task ID of the pending escalate_unaccepted_case task.",
    )

    # ── Notes ──────────────────────────────────────────────────────────────────
    doctor_notes: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Doctor rejection reason, or system escalation audit note.",
    )

    # ── Relationships ──────────────────────────────────────────────────────────
    doctor: Mapped[Doctor] = relationship("Doctor", back_populates="case_assignments")
    report: Mapped[SymptomReport] = relationship(
        "SymptomReport", back_populates="case_assignments"
    )
