"""
app/models/doctor.py

Module 05 — Doctor Dashboard: ORM model for doctor profiles.

Design decisions:
- doctor.specialty stores the raw SpecialistType code (e.g. "cardiologist").
  We use a plain String instead of a DB enum so adding a new specialist type
  never requires a migration — only specialist_kb.py + SpecialistType enum change.
- is_available lets a doctor temporarily go off-queue (holiday, overloaded).
- max_concurrent_cases caps how many offered assignments a doctor can hold at once
  before the routing layer skips them.
- The User ↔ Doctor join is 1:1 (unique constraint on user_id).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.case_assignment import CaseAssignment
    from app.models.user import User


class Doctor(Base):
    """
    Doctor profile table — linked 1:1 to a User account.

    Every doctor user has exactly one Doctor row that holds specialty,
    availability, and contact info used by the notification pipeline.
    """

    __tablename__ = "doctors"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # ── Professional Info ──────────────────────────────────────────────────────
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="SpecialistType code, e.g. 'cardiologist'. Indexed for routing lookups.",
    )
    license_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Contact ────────────────────────────────────────────────────────────────
    phone: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Availability ───────────────────────────────────────────────────────────
    is_available: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="False = doctor is off-queue; routing skips them.",
    )
    max_concurrent_cases: Mapped[int] = mapped_column(
        Integer,
        default=5,
        nullable=False,
        comment="Max simultaneous offered+accepted cases before routing skips this doctor.",
    )

    # ── Bio / Notes ────────────────────────────────────────────────────────────
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    case_assignments: Mapped[list[CaseAssignment]] = relationship(
        "CaseAssignment",
        back_populates="doctor",
        cascade="all, delete-orphan",
    )
