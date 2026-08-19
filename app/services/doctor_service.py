"""
app/services/doctor_service.py

Module 05 — Doctor Dashboard: business logic layer.

All database operations for the doctor dashboard live here, keeping route
handlers thin and testable.

Functions:
  get_or_create_doctor    — idempotent doctor profile creation
  get_doctor_by_user_id   — look up doctor profile for the authenticated user
  update_doctor           — PATCH profile fields
  get_doctor_queue        — paginated list of offered + accepted cases
  get_case_detail         — full case data for a single report in the queue
  accept_case             — mark an assignment ACCEPTED; revoke escalation task
  reject_case             — mark an assignment REJECTED; trigger immediate escalation
  update_report_status    — doctor closes a case (TRIAGED → CLOSED)
  get_analytics           — aggregate stats for the doctor's triage history
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.case_assignment import AssignmentStatus, CaseAssignment
from app.models.doctor import Doctor
from app.models.intake import ReportStatus, SymptomReport
from app.models.patient import Patient
from app.schemas.doctor import (
    DoctorAnalytics,
    DoctorCreate,
    DoctorQueueDetail,
    DoctorQueueItem,
    DoctorUpdate,
    PatientSummary,
    UrgencyBreakdown,
)

logger = logging.getLogger(__name__)


# ── Doctor Profile ─────────────────────────────────────────────────────────────

def create_doctor(db: Session, user_id: uuid.UUID, data: DoctorCreate) -> Doctor:
    """
    Create a doctor profile for an existing user.
    Raises 409 if a profile already exists for this user.
    """
    existing = db.query(Doctor).filter(Doctor.user_id == user_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Doctor profile already exists for this user.",
        )

    phone_conflict = db.query(Doctor).filter(Doctor.phone == data.phone).first()
    if phone_conflict:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A doctor with this phone number already exists.",
        )

    doctor = Doctor(
        user_id=user_id,
        full_name=data.full_name,
        specialty=data.specialty,
        phone=data.phone,
        email=data.email,
        license_number=data.license_number,
        department=data.department,
        bio=data.bio,
        max_concurrent_cases=data.max_concurrent_cases,
    )
    db.add(doctor)
    db.commit()
    db.refresh(doctor)
    logger.info(f"[DOCTOR] Created profile for user {user_id} — specialty: {doctor.specialty}")
    return doctor


def get_doctor_by_user_id(db: Session, user_id: uuid.UUID) -> Doctor:
    """Return the doctor profile for a user. Raises 404 if not found."""
    doctor = db.query(Doctor).filter(Doctor.user_id == user_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Doctor profile not found. Please create a profile first.",
        )
    return doctor


def get_doctor_by_id(db: Session, doctor_id: uuid.UUID) -> Doctor:
    """Admin lookup — get any doctor by primary key."""
    doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
    if not doctor:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Doctor {doctor_id} not found.",
        )
    return doctor


def update_doctor(db: Session, doctor: Doctor, data: DoctorUpdate) -> Doctor:
    """Apply partial update to doctor profile."""
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(doctor, field, value)
    db.commit()
    db.refresh(doctor)
    return doctor


# ── Doctor Queue ───────────────────────────────────────────────────────────────

def get_doctor_queue(
    db: Session,
    doctor_id: uuid.UUID,
    page: int = 1,
    limit: int = 20,
    status_filter: str | None = None,
) -> dict[str, Any]:
    """
    Paginated list of cases in this doctor's queue.

    Returns offered + accepted by default. Use status_filter to restrict.
    Each item is a DoctorQueueItem with report summary + routing overview.
    """
    query = (
        db.query(CaseAssignment, SymptomReport, Patient)
        .join(SymptomReport, CaseAssignment.report_id == SymptomReport.id)
        .join(Patient, SymptomReport.patient_id == Patient.id)
        .filter(CaseAssignment.doctor_id == doctor_id)
    )

    if status_filter:
        try:
            status_enum = AssignmentStatus(status_filter)
            query = query.filter(CaseAssignment.status == status_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid status filter: '{status_filter}'. "
                       f"Valid values: {[s.value for s in AssignmentStatus]}",
            )
    else:
        # Default: show active cases (offered + accepted)
        query = query.filter(
            CaseAssignment.status.in_([AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED])
        )

    total = query.count()
    rows = (
        query
        .order_by(CaseAssignment.offered_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    items = []
    for assignment, report, patient in rows:
        routing = report.routing_decision or {}
        items.append(
            DoctorQueueItem(
                assignment_id=assignment.id,
                assignment_status=assignment.status.value,
                offered_at=assignment.offered_at,
                responded_at=assignment.responded_at,
                escalation_count=assignment.escalation_count,
                report_id=report.id,
                raw_text=report.raw_text,
                severity_hint=report.severity_hint.value,
                status=report.status.value,
                urgency_level=report.urgency_level,
                specialist_recommendation=report.specialist_recommendation,
                created_at=report.created_at,
                routing_specialist=routing.get("specialist"),
                routing_confidence=routing.get("confidence"),
                routing_method=routing.get("routing_method"),
                patient=PatientSummary(
                    id=patient.id,
                    full_name=patient.full_name,
                    age=patient.age,
                    gender=patient.gender.value,
                    phone=patient.phone,
                ),
            )
        )

    return {"total": total, "page": page, "limit": limit, "cases": items}


def get_case_detail(
    db: Session,
    doctor_id: uuid.UUID,
    report_id: uuid.UUID,
) -> DoctorQueueDetail:
    """
    Full case detail — includes ai_analysis and routing_decision JSONB blobs.
    Validates that this doctor has an active assignment for the report.
    """
    row = (
        db.query(CaseAssignment, SymptomReport, Patient)
        .join(SymptomReport, CaseAssignment.report_id == SymptomReport.id)
        .join(Patient, SymptomReport.patient_id == Patient.id)
        .filter(
            CaseAssignment.doctor_id == doctor_id,
            CaseAssignment.report_id == report_id,
            CaseAssignment.status.in_([AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED]),
        )
        .order_by(CaseAssignment.offered_at.desc())
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Case not found in your queue. It may have been reassigned or closed.",
        )

    assignment, report, patient = row

    return DoctorQueueDetail(
        assignment_id=assignment.id,
        assignment_status=assignment.status.value,
        offered_at=assignment.offered_at,
        responded_at=assignment.responded_at,
        doctor_notes=assignment.doctor_notes,
        report_id=report.id,
        raw_text=report.raw_text,
        severity_hint=report.severity_hint.value,
        duration=report.duration,
        status=report.status.value,
        urgency_level=report.urgency_level,
        specialist_recommendation=report.specialist_recommendation,
        ai_analysis=report.ai_analysis,
        routing_decision=report.routing_decision,
        created_at=report.created_at,
        updated_at=report.updated_at,
        patient=PatientSummary(
            id=patient.id,
            full_name=patient.full_name,
            age=patient.age,
            gender=patient.gender.value,
            phone=patient.phone,
        ),
    )


# ── Accept / Reject ────────────────────────────────────────────────────────────

def accept_case(
    db: Session,
    doctor_id: uuid.UUID,
    report_id: uuid.UUID,
    notes: str | None = None,
) -> CaseAssignment:
    """
    Mark a CaseAssignment as ACCEPTED.

    Side effects:
      - Revokes the pending Celery escalation task (if still pending).
      - Notifies the patient that a doctor has accepted their case.
    """
    assignment = _get_active_assignment(db, doctor_id, report_id)

    # Revoke the escalation countdown task before it fires
    if assignment.celery_escalation_task_id:
        try:
            celery_app_instance = _get_celery()
            celery_app_instance.control.revoke(
                assignment.celery_escalation_task_id, terminate=False
            )
            logger.info(
                f"[DOCTOR] Revoked escalation task {assignment.celery_escalation_task_id} "
                f"for assignment {assignment.id}"
            )
        except Exception as exc:
            logger.warning(f"[DOCTOR] Could not revoke escalation task: {exc}")

    assignment.status = AssignmentStatus.ACCEPTED
    assignment.responded_at = datetime.now(tz=timezone.utc)
    if notes:
        assignment.doctor_notes = notes

    db.commit()
    db.refresh(assignment)

    # Notify patient (non-fatal)
    try:
        from app.services.notification_service import notification_service
        report = db.query(SymptomReport).filter(SymptomReport.id == report_id).first()
        patient = db.query(Patient).filter(Patient.id == report.patient_id).first()
        doctor = db.query(Doctor).filter(Doctor.id == doctor_id).first()
        if report and patient and doctor:
            notification_service.notify_patient_case_accepted(report, patient, doctor)
    except Exception as exc:
        logger.warning(f"[DOCTOR] Patient accept notification failed: {exc}")

    logger.info(f"[DOCTOR] ✓ Assignment {assignment.id} accepted by doctor {doctor_id}")
    return assignment


def reject_case(
    db: Session,
    doctor_id: uuid.UUID,
    report_id: uuid.UUID,
    reason: str,
) -> dict:
    """
    Mark a CaseAssignment as REJECTED and trigger immediate escalation.

    The rejection triggers an escalate_unaccepted_case task with countdown=0
    so the next doctor is found and notified without waiting.
    """
    assignment = _get_active_assignment(db, doctor_id, report_id)

    # Revoke existing escalation countdown (we'll trigger a new one immediately)
    if assignment.celery_escalation_task_id:
        try:
            _get_celery().control.revoke(assignment.celery_escalation_task_id, terminate=False)
        except Exception:
            pass

    assignment.status = AssignmentStatus.REJECTED
    assignment.responded_at = datetime.now(tz=timezone.utc)
    assignment.doctor_notes = reason
    db.commit()

    # Get the specialist for re-routing
    report = db.query(SymptomReport).filter(SymptomReport.id == report_id).first()
    specialist = report.specialist_recommendation or "general_practitioner"
    if report.routing_decision:
        specialist = report.routing_decision.get("specialist", specialist)

    # Trigger immediate escalation (countdown=0 → fires right away)
    from app.workers.tasks import escalate_unaccepted_case
    escalate_unaccepted_case.apply_async(
        args=[str(assignment.id), str(report_id), specialist],
        countdown=0,
    )

    logger.info(
        f"[DOCTOR] Assignment {assignment.id} rejected by doctor {doctor_id}. "
        f"Immediate escalation triggered."
    )
    return {
        "assignment_id": str(assignment.id),
        "status": "rejected",
        "escalation_triggered": True,
    }


# ── Status Update ──────────────────────────────────────────────────────────────

ALLOWED_STATUS_TRANSITIONS: dict[ReportStatus, list[ReportStatus]] = {
    ReportStatus.TRIAGED:    [ReportStatus.PROCESSING, ReportStatus.CLOSED],
    ReportStatus.PROCESSING: [ReportStatus.CLOSED],
}


def update_report_status(
    db: Session,
    doctor_id: uuid.UUID,
    report_id: uuid.UUID,
    new_status_str: str,
    notes: str | None = None,
) -> SymptomReport:
    """
    Allow a doctor to advance a report's status (e.g. TRIAGED → CLOSED).

    Validates:
      - Doctor has an ACCEPTED assignment for this report.
      - The transition is allowed by ALLOWED_STATUS_TRANSITIONS.
    """
    # Verify doctor owns an accepted assignment
    accepted = (
        db.query(CaseAssignment)
        .filter(
            CaseAssignment.doctor_id == doctor_id,
            CaseAssignment.report_id == report_id,
            CaseAssignment.status == AssignmentStatus.ACCEPTED,
        )
        .first()
    )
    if not accepted:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You have not accepted this case. Accept it before updating status.",
        )

    report = db.query(SymptomReport).filter(SymptomReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")

    try:
        new_status = ReportStatus(new_status_str)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status '{new_status_str}'. Valid: {[s.value for s in ReportStatus]}",
        )

    allowed = ALLOWED_STATUS_TRANSITIONS.get(report.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Cannot transition from '{report.status.value}' to '{new_status_str}'. "
                f"Allowed: {[s.value for s in allowed]}"
            ),
        )

    report.status = new_status
    if notes and accepted:
        if accepted.doctor_notes:
            accepted.doctor_notes += f"\n[STATUS UPDATE] {notes}"
        else:
            accepted.doctor_notes = f"[STATUS UPDATE] {notes}"
    db.commit()
    db.refresh(report)

    logger.info(
        f"[DOCTOR] Report {report_id} status updated to {new_status.value} "
        f"by doctor {doctor_id}"
    )
    return report


# ── Analytics ──────────────────────────────────────────────────────────────────

def get_analytics(db: Session, doctor_id: uuid.UUID) -> DoctorAnalytics:
    """
    Aggregate triage history stats for the authenticated doctor.

    Counts: offered / accepted / rejected / expired / closed cases.
    Computes: accept rate %, average response time in minutes, top specialty.
    """
    from sqlalchemy import func as sqlfunc

    assignments = (
        db.query(CaseAssignment)
        .filter(CaseAssignment.doctor_id == doctor_id)
        .all()
    )

    total_offered = len(assignments)
    total_accepted = sum(1 for a in assignments if a.status == AssignmentStatus.ACCEPTED)
    total_rejected = sum(1 for a in assignments if a.status == AssignmentStatus.REJECTED)
    total_expired  = sum(1 for a in assignments if a.status == AssignmentStatus.EXPIRED)

    accept_rate = round((total_accepted / total_offered * 100), 1) if total_offered > 0 else 0.0

    # Response time: mean (responded_at - offered_at) in minutes for accepted + rejected
    response_times_mins = []
    for a in assignments:
        if a.responded_at and a.status in (AssignmentStatus.ACCEPTED, AssignmentStatus.REJECTED):
            delta = a.responded_at - a.offered_at
            response_times_mins.append(delta.total_seconds() / 60)

    avg_response = (
        round(sum(response_times_mins) / len(response_times_mins), 1)
        if response_times_mins else None
    )

    # Closed cases: reports with status=CLOSED assigned to this doctor
    accepted_report_ids = [a.report_id for a in assignments if a.status == AssignmentStatus.ACCEPTED]
    closed_reports = []
    urgency_counts = {"critical": 0, "moderate": 0, "routine": 0}
    top_specialty = None

    if accepted_report_ids:
        accepted_reports = (
            db.query(SymptomReport)
            .filter(SymptomReport.id.in_(accepted_report_ids))
            .all()
        )
        closed_reports = [r for r in accepted_reports if r.status == ReportStatus.CLOSED]

        # Urgency breakdown (across all accepted)
        for r in accepted_reports:
            if r.urgency_level in urgency_counts:
                urgency_counts[r.urgency_level] += 1

        # Top specialty
        specialties: dict[str, int] = {}
        for r in accepted_reports:
            sp = r.specialist_recommendation
            if sp:
                specialties[sp] = specialties.get(sp, 0) + 1
        if specialties:
            top_specialty = max(specialties, key=specialties.get)  # type: ignore[arg-type]

    return DoctorAnalytics(
        doctor_id=doctor_id,
        total_cases_offered=total_offered,
        total_cases_accepted=total_accepted,
        total_cases_rejected=total_rejected,
        total_cases_expired=total_expired,
        accept_rate_pct=accept_rate,
        cases_closed=len(closed_reports),
        urgency_breakdown=UrgencyBreakdown(**urgency_counts),
        avg_response_minutes=avg_response,
        top_specialist_routed=top_specialty,
    )


# ── Private Helpers ────────────────────────────────────────────────────────────

def _get_active_assignment(
    db: Session, doctor_id: uuid.UUID, report_id: uuid.UUID
) -> CaseAssignment:
    """Fetch an OFFERED assignment for this doctor + report. Raises 404/409 otherwise."""
    assignment = (
        db.query(CaseAssignment)
        .filter(
            CaseAssignment.doctor_id == doctor_id,
            CaseAssignment.report_id == report_id,
            CaseAssignment.status == AssignmentStatus.OFFERED,
        )
        .order_by(CaseAssignment.offered_at.desc())
        .first()
    )
    if not assignment:
        # Check if already accepted
        accepted = (
            db.query(CaseAssignment)
            .filter(
                CaseAssignment.doctor_id == doctor_id,
                CaseAssignment.report_id == report_id,
                CaseAssignment.status == AssignmentStatus.ACCEPTED,
            )
            .first()
        )
        if accepted:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You have already accepted this case.",
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active (offered) assignment found for this case in your queue.",
        )
    return assignment


def _get_celery():
    """Lazy import to avoid circular deps at module load time."""
    from app.workers.celery_app import celery_app
    return celery_app
