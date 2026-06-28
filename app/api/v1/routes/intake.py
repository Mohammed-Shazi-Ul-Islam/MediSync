import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.schemas.intake import SymptomReportCreate, SymptomReportList, SymptomReportResponse
from app.services.intake_service import (
    create_symptom_report,
    get_patient_by_user_id,
    get_report_by_id,
    get_reports_by_patient,
)
from app.utils.dependencies import get_current_user, require_role

router = APIRouter(prefix="/intake", tags=["Patient Intake"])


@router.post(
    "",
    response_model=SymptomReportResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a symptom report for AI triage",
)
def submit_symptom_report(
    data: SymptomReportCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Submit a symptom report. Processing is asynchronous.

    Returns **202 Accepted** immediately — the AI triage pipeline runs in
    the background via Celery. Poll GET /intake/{id} to check status.

    Status lifecycle:
        pending → processing → triaged → closed

    Requires: patient profile (create via POST /patients first).
    """
    patient = get_patient_by_user_id(db, current_user.id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Patient profile not found. "
                "Please create your profile via POST /api/v1/patients first."
            ),
        )

    report = create_symptom_report(db, patient, data)
    return report


@router.get(
    "/my-reports",
    response_model=SymptomReportList,
    summary="List my symptom reports",
)
def get_my_reports(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(default=20, ge=1, le=100, description="Results per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Paginated list of all symptom reports for the authenticated patient.
    Ordered by most recent first.
    """
    patient = get_patient_by_user_id(db, current_user.id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Patient profile not found",
        )

    skip = (page - 1) * limit
    reports, total = get_reports_by_patient(db, patient.id, skip, limit)
    return SymptomReportList(total=total, page=page, limit=limit, reports=reports)


@router.get(
    "/{report_id}",
    response_model=SymptomReportResponse,
    summary="Get report status and AI triage results",
)
def get_report_status(
    report_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Fetch a specific symptom report by ID.

    - **Patients**: can only view their own reports
    - **Doctors / Admins**: can view any report

    When status is `triaged`, the `urgency_level`, `specialist_recommendation`,
    and `ai_analysis` fields will be populated (Module 02).
    """
    report = get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report {report_id} not found",
        )

    # Patients can only access their own reports
    if current_user.role == UserRole.PATIENT:
        patient = get_patient_by_user_id(db, current_user.id)
        if not patient or report.patient_id != patient.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to view this report",
            )

    return report
