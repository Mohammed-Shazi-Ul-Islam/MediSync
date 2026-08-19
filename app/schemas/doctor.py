"""
app/schemas/doctor.py

Module 05 — Doctor Dashboard: Pydantic models for doctor profiles and dashboard.

Schema hierarchy:
  DoctorCreate  → POST /doctors (registration body)
  DoctorRead    → all GET doctor responses
  DoctorUpdate  → PATCH /doctors/me (partial update)
  DoctorQueueItem → one entry in the doctor's active case queue
  DoctorAnalytics → aggregate triage history stats
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


# ── Doctor Profile Schemas ─────────────────────────────────────────────────────

class DoctorCreate(BaseModel):
    """
    Body for POST /api/v1/doctors.
    Requires an existing user account with role=doctor.
    """
    full_name: str = Field(..., min_length=2, max_length=255, examples=["Dr. Sarah Ahmed"])
    specialty: str = Field(
        ...,
        description="SpecialistType code, e.g. 'cardiologist'. Must match a known specialist type.",
        examples=["cardiologist"],
    )
    phone: str = Field(..., min_length=7, max_length=20, examples=["+919876543210"])
    email: EmailStr | None = Field(default=None, examples=["sarah@hospital.com"])
    license_number: str | None = Field(default=None, max_length=100, examples=["MCI-12345"])
    department: str | None = Field(default=None, max_length=255, examples=["Cardiology - ICU"])
    bio: str | None = Field(default=None, max_length=2000)
    max_concurrent_cases: int = Field(default=5, ge=1, le=50)


class DoctorRead(BaseModel):
    """Response model for any doctor profile query."""
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    specialty: str
    phone: str
    email: str | None
    license_number: str | None
    department: str | None
    bio: str | None
    is_available: bool
    max_concurrent_cases: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DoctorUpdate(BaseModel):
    """
    Body for PATCH /api/v1/doctors/me.
    All fields optional — only supplied fields are updated.
    """
    full_name: str | None = Field(default=None, min_length=2, max_length=255)
    phone: str | None = Field(default=None, min_length=7, max_length=20)
    email: EmailStr | None = None
    department: str | None = Field(default=None, max_length=255)
    bio: str | None = None
    is_available: bool | None = None
    max_concurrent_cases: int | None = Field(default=None, ge=1, le=50)


# ── Doctor Queue Schemas ───────────────────────────────────────────────────────

class PatientSummary(BaseModel):
    """Minimal patient info embedded in the doctor's queue view."""
    id: uuid.UUID
    full_name: str
    age: int
    gender: str
    phone: str

    model_config = {"from_attributes": True}


class DoctorQueueItem(BaseModel):
    """
    One case in a doctor's queue — returned by GET /doctors/me/queue.

    Combines report summary, triage result, and assignment state into
    a single flat object so the dashboard doesn't need additional lookups.
    """
    # Assignment info
    assignment_id: uuid.UUID
    assignment_status: str
    offered_at: datetime
    responded_at: datetime | None
    escalation_count: int

    # Report summary
    report_id: uuid.UUID
    raw_text: str
    severity_hint: str
    status: str
    urgency_level: str | None
    specialist_recommendation: str | None
    created_at: datetime

    # Routing decision summary
    routing_specialist: str | None = None
    routing_confidence: float | None = None
    routing_method: str | None = None

    # Patient info
    patient: PatientSummary | None

    model_config = {"from_attributes": True}


class DoctorQueueDetail(BaseModel):
    """
    Full case detail — returned by GET /doctors/me/queue/{report_id}.
    Includes the full ai_analysis and routing_decision JSONB blobs.
    """
    assignment_id: uuid.UUID
    assignment_status: str
    offered_at: datetime
    responded_at: datetime | None
    doctor_notes: str | None

    report_id: uuid.UUID
    raw_text: str
    severity_hint: str
    duration: str | None
    status: str
    urgency_level: str | None
    specialist_recommendation: str | None
    ai_analysis: dict | None
    routing_decision: dict | None
    created_at: datetime
    updated_at: datetime

    patient: PatientSummary | None

    model_config = {"from_attributes": True}


# ── Accept / Reject / Status Update Schemas ───────────────────────────────────

class CaseAcceptBody(BaseModel):
    """Optional body for POST /doctors/me/queue/{report_id}/accept."""
    notes: str | None = Field(default=None, max_length=2000)


class CaseRejectBody(BaseModel):
    """Required reason for POST /doctors/me/queue/{report_id}/reject."""
    reason: str = Field(..., min_length=3, max_length=2000, examples=["Out of specialty scope"])


class ReportStatusUpdate(BaseModel):
    """Body for PATCH /doctors/me/queue/{report_id}/status."""
    new_status: str = Field(
        ...,
        examples=["closed"],
        description="New report status. Allowed: 'processing', 'triaged', 'closed'.",
    )
    notes: str | None = Field(default=None, max_length=2000)


# ── Analytics Schemas ──────────────────────────────────────────────────────────

class UrgencyBreakdown(BaseModel):
    critical: int = 0
    moderate: int = 0
    routine: int = 0


class DoctorAnalytics(BaseModel):
    """
    Aggregated triage history for GET /doctors/me/analytics.

    All counts are across all time unless a date_from / date_to query param is added.
    avg_response_minutes is the mean time from offered_at to responded_at.
    """
    doctor_id: uuid.UUID
    total_cases_offered: int
    total_cases_accepted: int
    total_cases_rejected: int
    total_cases_expired: int
    accept_rate_pct: float = Field(description="Percentage of offered cases accepted (0–100)")
    cases_closed: int
    urgency_breakdown: UrgencyBreakdown
    avg_response_minutes: float | None = Field(
        default=None,
        description="Mean accept/reject response time in minutes. None if no responses yet.",
    )
    top_specialist_routed: str | None = Field(
        default=None,
        description="Most frequent specialty in accepted cases.",
    )
