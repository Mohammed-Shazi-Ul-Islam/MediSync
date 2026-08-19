"""
app/workers/tasks.py

Celery task definitions for MediSync.

Module 02 — AI Triage Engine:
  analyze_symptom_report invokes the full LangChain + Gemini + ChromaDB RAG
  pipeline via triage_service.run_triage_pipeline(). Results are written back
  to the symptom_reports table and the report is marked TRIAGED.

Module 03 — Specialist Router:
  Immediately after triage, the same Celery task runs the HybridSpecialistRouter
  to map the TriageResult symptom cluster to the correct specialist. The
  RoutingDecision is persisted in symptom_reports.routing_decision (JSONB).
  Routing errors are caught and logged but do NOT cause the task to fail —
  triage correctness takes precedence.

Module 04 — Async Notification Pipeline:
  After routing, the task:
    1. Finds an available doctor matching the routed specialist type.
    2. Creates a CaseAssignment row (status=offered).
    3. Sends SMS + email alert to the doctor.
    4. Sends SMS + email confirmation to the patient.
    5. Schedules escalate_unaccepted_case to fire in N minutes via countdown.

  escalate_unaccepted_case (separate task):
    Checks if the assignment was accepted. If not:
      - Marks it expired, finds next available doctor, repeats.
      - If max escalations reached, fires admin alert.

  send_notification_task (separate thin wrapper task):
    Allows scheduling notification sends from the Celery queue without
    blocking the main triage task.

Why bind=True?
  Gives the task access to `self` — needed to call self.retry() on failure.

Why max_retries=3?
  LLM API calls can fail transiently. We retry up to 3 times with a 60-second
  countdown (exponential backoff would be added in production).
"""

import logging
import uuid

from app.database import SessionLocal
from app.models.intake import ReportStatus, SymptomReport
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


# ── Helper: find an available doctor for a specialty ─────────────────────────

def _find_available_doctor(db, specialty: str, exclude_doctor_ids: list[str] | None = None):
    """
    Query the doctors table for an available doctor matching the given specialty.

    exclude_doctor_ids: list of doctor ID strings already tried (escalation chain).
    Returns a Doctor ORM object or None.

    Load balancing strategy: returns the doctor with the fewest active
    (offered + accepted) assignments to distribute load fairly.
    """
    from sqlalchemy import func as sqlfunc
    from app.models.doctor import Doctor
    from app.models.case_assignment import CaseAssignment, AssignmentStatus

    exclude_ids = [uuid.UUID(did) for did in (exclude_doctor_ids or [])]

    # Subquery: count active assignments per doctor
    active_counts = (
        db.query(
            CaseAssignment.doctor_id,
            sqlfunc.count(CaseAssignment.id).label("active_count"),
        )
        .filter(CaseAssignment.status.in_([AssignmentStatus.OFFERED, AssignmentStatus.ACCEPTED]))
        .group_by(CaseAssignment.doctor_id)
        .subquery()
    )

    doctor = (
        db.query(Doctor)
        .outerjoin(active_counts, Doctor.id == active_counts.c.doctor_id)
        .filter(
            Doctor.specialty == specialty,
            Doctor.is_available == True,  # noqa: E712
            Doctor.id.notin_(exclude_ids),
        )
        # Doctors with fewer active cases first; NULL means 0 active cases
        .order_by(
            sqlfunc.coalesce(active_counts.c.active_count, 0).asc()
        )
        # Only assign if doctor hasn't hit their concurrent case cap
        .filter(
            sqlfunc.coalesce(active_counts.c.active_count, 0) < Doctor.max_concurrent_cases
        )
        .first()
    )
    return doctor


# ── Main Pipeline Task ────────────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.tasks.analyze_symptom_report",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def analyze_symptom_report(self, report_id: str) -> dict:
    """
    AI Triage Pipeline — entry point called by Celery for every new symptom report.

    Called by intake_service.py immediately after a SymptomReport is saved.
    This task runs in a separate Celery worker process (medisync_worker container).

    Steps:
        1. Load the SymptomReport from the database.
        2. Call triage_service.run_triage_pipeline() which:
               a. Embeds the symptom text and retrieves top-K medical KB docs
               b. Builds a prompt with the retrieved context
               c. Calls Gemini 1.5 Flash for urgency classification + extraction
               d. Parses the response into a TriageResult Pydantic model
        3. Write urgency_level, specialist_recommendation, and ai_analysis to DB.
        4. Mark the report as TRIAGED.
        5. Run specialist routing (Module 03).
        6. Assign to doctor + send notifications (Module 04).
    """
    # Deferred import to avoid circular dependencies at module load time
    from app.services.triage_service import triage_service

    logger.info(f"[TRIAGE] ▶ Received report {report_id} for AI analysis")

    db = SessionLocal()
    try:
        report = (
            db.query(SymptomReport)
            .filter(SymptomReport.id == report_id)
            .first()
        )

        if not report:
            logger.error(f"[TRIAGE] ✗ Report {report_id} not found in DB")
            return {"status": "error", "message": "Report not found"}

        # ── Module 02: Full AI Triage Pipeline ────────────────────────────────
        logger.info(f"[TRIAGE] Running AI pipeline for report {report_id}")

        severity_hint = report.severity_hint.value if report.severity_hint else "unknown"
        triage_result = triage_service.run_triage_pipeline(
            raw_text=report.raw_text,
            severity_hint=severity_hint,
        )

        # Write triage results to DB
        report.urgency_level = triage_result.urgency_level
        report.specialist_recommendation = triage_result.specialist_recommendation
        report.ai_analysis = triage_service.result_to_db_dict(triage_result)
        report.status = ReportStatus.TRIAGED
        db.commit()
        db.refresh(report)
        # ──────────────────────────────────────────────────────────────────────

        logger.info(
            f"[TRIAGE] ✓ Report {report_id} triaged: "
            f"urgency={triage_result.urgency_level}, "
            f"specialist={triage_result.specialist_recommendation}, "
            f"confidence={triage_result.confidence}"
        )

        # ── Module 03: Specialist Routing ──────────────────────────────────────
        routing_decision = None
        try:
            from app.services.specialist_router import hybrid_router
            routing_decision = hybrid_router.route(triage_result)
            report.routing_decision = routing_decision.model_dump()
            db.commit()
            logger.info(
                f"[ROUTER] ✓ Report {report_id} routed: "
                f"specialist={routing_decision.specialist}, "
                f"confidence={routing_decision.confidence}, "
                f"method={routing_decision.routing_method}"
            )
        except Exception as routing_exc:
            # Routing failure is non-fatal — triage result is already saved
            logger.error(
                f"[ROUTER] ✗ Routing failed for report {report_id} "
                f"(triage result preserved): {routing_exc}"
            )
        # ──────────────────────────────────────────────────────────────────────

        # ── Module 04: Notification + Doctor Assignment ────────────────────────
        assignment_id = None
        try:
            assignment_id = _assign_and_notify(
                db=db,
                report=report,
                specialist=routing_decision.specialist if routing_decision else triage_result.specialist_recommendation,
                escalation_count=0,
                previously_tried=[],
            )
        except Exception as notify_exc:
            # Notification failure is non-fatal — triage + routing preserved
            logger.error(
                f"[NOTIFY] ✗ Assignment/notification failed for report {report_id}: {notify_exc}"
            )
        # ──────────────────────────────────────────────────────────────────────

        # ── Module 06: Audit log — triage completed ────────────────────────────
        try:
            from app.services.audit_service import log_event
            from app.models.audit_log import AuditEventType
            log_event(
                db=db,
                event_type=AuditEventType.TRIAGE_COMPLETED,
                resource_type="symptom_report",
                resource_id=report.id,
                payload={
                    "urgency_level": triage_result.urgency_level,
                    "specialist_recommendation": triage_result.specialist_recommendation,
                    "confidence": triage_result.confidence,
                    "routing": routing_decision.model_dump() if routing_decision else None,
                },
            )
        except Exception as audit_exc:
            logger.warning(f"[TRIAGE] Audit log write failed (non-fatal): {audit_exc}")
        # ──────────────────────────────────────────────────────────────────────

        return {
            "status": "triaged",
            "report_id": report_id,
            "urgency_level": triage_result.urgency_level,
            "specialist": triage_result.specialist_recommendation,
            "confidence": triage_result.confidence,
            "routing": routing_decision.model_dump() if routing_decision else None,
            "assignment_id": str(assignment_id) if assignment_id else None,
        }

    except Exception as exc:
        logger.error(f"[TRIAGE] ✗ Error processing report {report_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)

    finally:
        db.close()


# ── Module 04: Assignment + Notification Helper ───────────────────────────────

def _assign_and_notify(
    db,
    report: SymptomReport,
    specialist: str,
    escalation_count: int,
    previously_tried: list[str],
) -> str | None:
    """
    Find an available doctor, create a CaseAssignment, send alerts,
    and schedule the escalation countdown task.

    Returns the assignment ID string, or None if no doctor found.
    """
    from app.config import get_settings
    from app.models.case_assignment import CaseAssignment, AssignmentStatus
    from app.models.patient import Patient
    from app.services.notification_service import notification_service

    settings = get_settings()

    # Find an available, non-exhausted doctor
    doctor = _find_available_doctor(db, specialty=specialist, exclude_doctor_ids=previously_tried)

    if not doctor:
        logger.warning(
            f"[NOTIFY] No available doctor found for specialty '{specialist}' "
            f"(report {report.id}, escalation #{escalation_count})"
        )
        return None

    # Load patient for notification
    patient = db.query(Patient).filter(Patient.id == report.patient_id).first()

    # Create CaseAssignment row
    assignment = CaseAssignment(
        report_id=report.id,
        doctor_id=doctor.id,
        status=AssignmentStatus.OFFERED,
        escalation_count=escalation_count,
    )
    db.add(assignment)

    # Update denormalised FK on report
    report.assigned_doctor_id = doctor.id
    db.commit()
    db.refresh(assignment)

    assignment_id = str(assignment.id)
    logger.info(
        f"[NOTIFY] Case assigned: report={report.id}, doctor={doctor.full_name}, "
        f"assignment={assignment_id}, escalation_count={escalation_count}"
    )

    # Schedule escalation countdown
    countdown_seconds = settings.notification_escalation_minutes * 60
    escalation_task = escalate_unaccepted_case.apply_async(
        args=[assignment_id, str(report.id), specialist],
        countdown=countdown_seconds,
    )

    # Store escalation task ID so we can revoke it on accept
    assignment.celery_escalation_task_id = escalation_task.id
    db.commit()

    # Send notifications (non-fatal — already in outer try/except)
    if patient:
        notification_service.notify_doctor_alert(doctor, report, patient, escalation_count)
        if escalation_count == 0:
            # Only send patient triage result notification on first assignment
            reasoning = ""
            if report.ai_analysis:
                reasoning = report.ai_analysis.get("reasoning", "")
            notification_service.notify_patient_triaged(
                report=report,
                patient=patient,
                urgency=report.urgency_level or "unknown",
                specialist=specialist,
                reasoning=reasoning,
            )

    return assignment_id


# ── Module 04: Escalation Task ────────────────────────────────────────────────

@celery_app.task(
    name="app.workers.tasks.escalate_unaccepted_case",
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def escalate_unaccepted_case(
    self, assignment_id: str, report_id: str, specialist: str
) -> dict:
    """
    Fires N minutes after a CaseAssignment is created (via countdown).

    Checks if the doctor accepted. If not:
      - Marks the assignment as EXPIRED.
      - Collects all previously tried doctor IDs.
      - Finds the next available doctor.
      - Creates a new CaseAssignment (status=offered) and re-sends alerts.
      - If max escalations reached, sends admin alert.

    This task is only a no-op if the assignment was already accepted or rejected
    before the countdown fired.
    """
    from app.config import get_settings
    from app.models.case_assignment import CaseAssignment, AssignmentStatus
    from app.models.intake import SymptomReport
    from app.services.notification_service import notification_service

    settings = get_settings()
    db = SessionLocal()

    try:
        assignment = (
            db.query(CaseAssignment)
            .filter(CaseAssignment.id == uuid.UUID(assignment_id))
            .first()
        )

        if not assignment:
            logger.warning(f"[ESCALATION] Assignment {assignment_id} not found — skipping")
            return {"status": "skipped", "reason": "assignment_not_found"}

        # If doctor already responded, nothing to do
        if assignment.status in (AssignmentStatus.ACCEPTED, AssignmentStatus.REJECTED):
            logger.info(
                f"[ESCALATION] Assignment {assignment_id} already {assignment.status.value} — no escalation needed"
            )
            return {"status": "no_op", "assignment_status": assignment.status.value}

        # Mark current assignment as EXPIRED
        from datetime import datetime, timezone
        assignment.status = AssignmentStatus.EXPIRED
        assignment.doctor_notes = (
            f"Auto-expired after {settings.notification_escalation_minutes} minutes "
            f"with no response (escalation #{assignment.escalation_count})."
        )
        db.commit()

        new_escalation_count = assignment.escalation_count + 1

        logger.info(
            f"[ESCALATION] Assignment {assignment_id} expired — "
            f"escalation #{new_escalation_count} starting for report {report_id}"
        )

        # Check max escalations
        if new_escalation_count > settings.notification_max_escalations:
            logger.error(
                f"[ESCALATION] ⛔ Report {report_id} reached max escalations "
                f"({settings.notification_max_escalations}). Admin alert fired."
            )
            notification_service.notify_admin_max_escalations(report_id, new_escalation_count)
            return {
                "status": "max_escalations_reached",
                "report_id": report_id,
                "escalation_count": new_escalation_count,
            }

        # Collect all previously tried doctor IDs (to skip them)
        report = db.query(SymptomReport).filter(SymptomReport.id == uuid.UUID(report_id)).first()
        if not report:
            logger.error(f"[ESCALATION] Report {report_id} not found — cannot escalate")
            return {"status": "error", "reason": "report_not_found"}

        all_tried = [
            str(a.doctor_id)
            for a in db.query(CaseAssignment).filter(
                CaseAssignment.report_id == uuid.UUID(report_id)
            ).all()
        ]

        # Find next doctor and create new assignment
        new_assignment_id = _assign_and_notify(
            db=db,
            report=report,
            specialist=specialist,
            escalation_count=new_escalation_count,
            previously_tried=all_tried,
        )

        if new_assignment_id is None:
            logger.error(
                f"[ESCALATION] No more doctors available for specialty '{specialist}' "
                f"— report {report_id} cannot be escalated further"
            )
            notification_service.notify_admin_max_escalations(report_id, new_escalation_count)
            return {
                "status": "no_doctors_available",
                "report_id": report_id,
                "specialty": specialist,
            }

        # ── Module 06: Audit log — escalation occurred ─────────────────────────
        try:
            from app.services.audit_service import log_event
            from app.models.audit_log import AuditEventType
            log_event(
                db=db,
                event_type=AuditEventType.CASE_ESCALATED,
                resource_type="symptom_report",
                resource_id=report_id,
                payload={
                    "expired_assignment": assignment_id,
                    "new_assignment": new_assignment_id,
                    "escalation_count": new_escalation_count,
                    "specialist": specialist,
                },
            )
        except Exception as audit_exc:
            logger.warning(f"[ESCALATION] Audit log write failed (non-fatal): {audit_exc}")
        # ──────────────────────────────────────────────────────────────────────

        return {
            "status": "escalated",
            "report_id": report_id,
            "expired_assignment": assignment_id,
            "new_assignment": new_assignment_id,
            "escalation_count": new_escalation_count,
        }


    except Exception as exc:
        logger.error(f"[ESCALATION] ✗ Error escalating assignment {assignment_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=30)

    finally:
        db.close()


# ── Module 04: Thin Notification Task (for deferred sends) ───────────────────

@celery_app.task(
    name="app.workers.tasks.send_notification_task",
    bind=False,
    max_retries=2,
    default_retry_delay=30,
)
def send_notification_task(payload: dict) -> dict:
    """
    Thin Celery wrapper for sending a single notification from the queue.

    Accepts a NotificationPayload dict. This allows callers to schedule
    notification sends without blocking the main triage task.

    payload keys: channel, recipient_phone, recipient_email, subject, body,
                  html_body, report_id, doctor_id
    """
    from app.schemas.notification import NotificationPayload
    from app.services.notification_service import notification_service

    try:
        p = NotificationPayload(**payload)

        if p.channel in ("sms", "both") and p.recipient_phone:
            notification_service.send_sms(p.recipient_phone, p.body)

        if p.channel in ("email", "both") and p.recipient_email:
            notification_service.send_email(
                to=p.recipient_email,
                subject=p.subject,
                body=p.body,
                html_body=p.html_body,
            )

        logger.info(
            f"[NOTIFY] send_notification_task complete: "
            f"channel={p.channel}, report_id={p.report_id}"
        )
        return {"status": "sent", "channel": p.channel}

    except Exception as exc:
        logger.error(f"[NOTIFY] send_notification_task failed: {exc}")
        return {"status": "error", "error": str(exc)}
