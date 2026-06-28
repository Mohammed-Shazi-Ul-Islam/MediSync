import uuid

from sqlalchemy.orm import Session

from app.models.intake import ReportStatus, SymptomReport
from app.models.patient import Patient
from app.schemas.intake import SymptomReportCreate


# ── Patient Helpers ────────────────────────────────────────────────────────────

def get_patient_by_user_id(db: Session, user_id: uuid.UUID) -> Patient | None:
    """Fetch a patient profile by their auth user ID."""
    return db.query(Patient).filter(Patient.user_id == user_id).first()


def get_patient_by_id(db: Session, patient_id: uuid.UUID) -> Patient | None:
    return db.query(Patient).filter(Patient.id == patient_id).first()


# ── Symptom Report CRUD ────────────────────────────────────────────────────────

def create_symptom_report(
    db: Session,
    patient: Patient,
    data: SymptomReportCreate,
) -> SymptomReport:
    """
    Persist a new SymptomReport and immediately dispatch to the AI triage queue.

    Import of analyze_symptom_report is deferred inside the function body to
    avoid circular imports at module load time (celery_app → config → this module).
    The task is called via .delay() which is non-blocking — control returns
    immediately and the API responds with 202 Accepted.
    """
    # Lazy import to avoid circular dependency
    from app.workers.tasks import analyze_symptom_report

    report = SymptomReport(
        patient_id=patient.id,
        raw_text=data.raw_text,
        structured_symptoms=data.structured_symptoms,
        severity_hint=data.severity_hint,
        duration=data.duration,
        status=ReportStatus.PENDING,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    # Dispatch async task — returns immediately with a Celery AsyncResult
    task = analyze_symptom_report.delay(str(report.id))

    # Store task ID so the client can track status via GET /intake/{id}
    report.celery_task_id = task.id
    report.status = ReportStatus.PROCESSING
    db.commit()
    db.refresh(report)

    return report


def get_report_by_id(db: Session, report_id: uuid.UUID) -> SymptomReport | None:
    return db.query(SymptomReport).filter(SymptomReport.id == report_id).first()


def get_reports_by_patient(
    db: Session,
    patient_id: uuid.UUID,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[SymptomReport], int]:
    """Returns (paginated_reports, total_count) for a given patient."""
    query = db.query(SymptomReport).filter(SymptomReport.patient_id == patient_id)
    total = query.count()
    reports = (
        query.order_by(SymptomReport.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return reports, total
