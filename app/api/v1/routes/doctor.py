"""
app/api/v1/routes/doctor.py

Module 05 — Doctor Dashboard API: HTTP route handlers.

All endpoints require a valid JWT. Role checks enforce:
  - Doctors can only manage their own profile and queue.
  - Admins can view any doctor.

Route map:
  POST   /doctors                              → create_doctor_profile
  GET    /doctors/me                           → get_my_profile
  PATCH  /doctors/me                           → update_my_profile
  GET    /doctors/me/queue                     → get_my_queue
  GET    /doctors/me/queue/{report_id}         → get_case_detail
  POST   /doctors/me/queue/{report_id}/accept  → accept_case
  POST   /doctors/me/queue/{report_id}/reject  → reject_case
  PATCH  /doctors/me/queue/{report_id}/status  → update_case_status
  GET    /doctors/me/analytics                 → get_my_analytics
  GET    /doctors/{doctor_id}                  → get_doctor_by_id (admin)
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

import app.services.doctor_service as doctor_service
from app.database import get_db
from app.models.audit_log import AuditEventType
from app.models.user import User, UserRole
from app.schemas.doctor import (
    CaseAcceptBody,
    CaseRejectBody,
    DoctorAnalytics,
    DoctorCreate,
    DoctorQueueDetail,
    DoctorRead,
    DoctorUpdate,
    ReportStatusUpdate,
)
from app.services import audit_service
from app.utils.dependencies import require_role

router = APIRouter(prefix="/doctors", tags=["Doctor Dashboard"])


# ── Profile Endpoints ──────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=DoctorRead,
    status_code=201,
    summary="Create doctor profile",
    description=(
        "Create a doctor profile linked to the authenticated user account. "
        "The user must have role=doctor. Each user can have only one doctor profile."
    ),
)
def create_doctor_profile(
    body: DoctorCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR, UserRole.ADMIN)),
):
    return doctor_service.create_doctor(db, current_user.id, body)


@router.get(
    "/me",
    response_model=DoctorRead,
    summary="Get my doctor profile",
)
def get_my_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    return doctor_service.get_doctor_by_user_id(db, current_user.id)


@router.patch(
    "/me",
    response_model=DoctorRead,
    summary="Update my doctor profile",
    description=(
        "Partially update doctor profile. Only supplied fields are changed. "
        "Use is_available=false to temporarily go off-queue."
    ),
)
def update_my_profile(
    body: DoctorUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    return doctor_service.update_doctor(db, doc, body)


# ── Queue Endpoints ────────────────────────────────────────────────────────────

@router.get(
    "/me/queue",
    summary="Get my case queue",
    description=(
        "Paginated list of cases currently in the doctor's queue. "
        "By default returns offered + accepted cases. "
        "Use ?status=offered|accepted|rejected|expired to filter."
    ),
)
def get_my_queue(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Items per page"),
    status: str | None = Query(
        default=None,
        description="Filter by assignment status: offered, accepted, rejected, expired",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    return doctor_service.get_doctor_queue(db, doc.id, page, limit, status)


@router.get(
    "/me/queue/{report_id}",
    response_model=DoctorQueueDetail,
    summary="Get full case detail",
    description=(
        "Full case detail including the raw AI analysis JSONB and routing decision "
        "for a report currently in the doctor's active queue."
    ),
)
def get_my_case_detail(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    return doctor_service.get_case_detail(db, doc.id, report_id)


@router.post(
    "/me/queue/{report_id}/accept",
    summary="Accept a case",
    description=(
        "Accept an offered case. This cancels the escalation countdown, "
        "marks the assignment as accepted, and notifies the patient. "
        "Returns the updated assignment details."
    ),
)
def accept_my_case(
    request: Request,
    report_id: uuid.UUID,
    body: CaseAcceptBody = CaseAcceptBody(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    assignment = doctor_service.accept_case(db, doc.id, report_id, body.notes)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.CASE_ACCEPTED,
        resource_type="case_assignment",
        resource_id=assignment.id,
        actor=current_user,
        payload={
            "report_id": str(report_id),
            "doctor_id": str(doc.id),
            "notes": body.notes,
        },
        request=request,
    )

    return {
        "assignment_id": str(assignment.id),
        "status": assignment.status.value,
        "responded_at": assignment.responded_at.isoformat() if assignment.responded_at else None,
        "message": "Case accepted. The patient has been notified.",
    }


@router.post(
    "/me/queue/{report_id}/reject",
    summary="Reject a case",
    description=(
        "Reject an offered case with a required reason. "
        "Triggers immediate escalation to the next available doctor of the same specialty."
    ),
)
def reject_my_case(
    request: Request,
    report_id: uuid.UUID,
    body: CaseRejectBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    result = doctor_service.reject_case(db, doc.id, report_id, body.reason)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.CASE_REJECTED,
        resource_type="symptom_report",
        resource_id=report_id,
        actor=current_user,
        payload={
            "doctor_id": str(doc.id),
            "reason": body.reason,
        },
        request=request,
    )

    return result


@router.patch(
    "/me/queue/{report_id}/status",
    summary="Update report status",
    description=(
        "Update the lifecycle status of a report the doctor has accepted. "
        "Allowed transitions: TRIAGED → PROCESSING → CLOSED. "
        "Use CLOSED to indicate the consultation is complete."
    ),
)
def update_case_status(
    request: Request,
    report_id: uuid.UUID,
    body: ReportStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    report = doctor_service.update_report_status(
        db, doc.id, report_id, body.new_status, body.notes
    )

    # Emit CASE_CLOSED audit event when a case is explicitly closed
    from app.models.intake import ReportStatus
    if body.new_status == ReportStatus.CLOSED:
        audit_service.log_event(
            db=db,
            event_type=AuditEventType.CASE_CLOSED,
            resource_type="symptom_report",
            resource_id=report_id,
            actor=current_user,
            payload={
                "doctor_id": str(doc.id),
                "notes": body.notes,
                "new_status": body.new_status.value,
            },
            request=request,
        )

    return {
        "report_id": str(report.id),
        "new_status": report.status.value,
        "message": f"Report status updated to '{report.status.value}'.",
    }


# ── Analytics ──────────────────────────────────────────────────────────────────

@router.get(
    "/me/analytics",
    response_model=DoctorAnalytics,
    summary="Get my triage analytics",
    description=(
        "Aggregated statistics across all cases ever offered to this doctor: "
        "total offered/accepted/rejected/expired, accept rate %, "
        "urgency breakdown, average response time, and top specialty."
    ),
)
def get_my_analytics(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DOCTOR)),
):
    doc = doctor_service.get_doctor_by_user_id(db, current_user.id)
    return doctor_service.get_analytics(db, doc.id)


# ── Admin Endpoint ─────────────────────────────────────────────────────────────

@router.get(
    "/{doctor_id}",
    response_model=DoctorRead,
    summary="Get doctor by ID (admin)",
    description="Admin-only endpoint to retrieve any doctor profile by UUID.",
)
def get_doctor_profile_by_id(
    doctor_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    return doctor_service.get_doctor_by_id(db, doctor_id)
