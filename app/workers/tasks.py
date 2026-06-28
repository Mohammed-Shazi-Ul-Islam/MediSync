"""
app/workers/tasks.py

Celery task definitions for MediSync.

Module 01 — Stub:
  analyze_symptom_report is defined here as a stub that acknowledges receipt
  and logs the report ID. The real LangChain + Gemini pipeline will be
  implemented in Module 02 and replace the TODO block below.

Why bind=True?
  Gives the task access to `self` — needed to call self.retry() on failure.

Why max_retries=3?
  LLM API calls can fail transiently. We retry up to 3 times with a 60-second
  countdown (exponential backoff would be added in production).
"""

import logging

from app.database import SessionLocal
from app.models.intake import ReportStatus, SymptomReport
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="app.workers.tasks.analyze_symptom_report",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def analyze_symptom_report(self, report_id: str) -> dict:
    """
    AI Triage Pipeline — entry point.

    Called by intake_service.py immediately after a SymptomReport is saved.
    This task runs in a separate Celery worker process (medisync_worker container).

    Current state (Module 01): Stub — just acknowledges receipt.
    Module 02 will replace the TODO block with:
        - LangChain chain invocation
        - Gemini LLM call for urgency classification
        - RAG retrieval from ChromaDB medical knowledge base
        - Structured extraction of symptoms
        - Update report with results
    """
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

        # ── TODO (Module 02): Replace stub with full AI pipeline ───────────────
        # from app.services.triage_service import run_triage_pipeline
        # result = run_triage_pipeline(report.raw_text, report.structured_symptoms)
        # report.urgency_level = result.urgency_level
        # report.specialist_recommendation = result.specialist
        # report.ai_analysis = result.dict()
        # report.status = ReportStatus.TRIAGED
        # ──────────────────────────────────────────────────────────────────────

        logger.info(
            f"[TRIAGE] ✓ Report {report_id} acknowledged. "
            "Awaiting Module 02 AI engine implementation."
        )

        return {
            "status": "acknowledged",
            "report_id": report_id,
            "message": "Queued for AI triage (Module 02 pending)",
        }

    except Exception as exc:
        logger.error(f"[TRIAGE] ✗ Error processing report {report_id}: {exc}")
        db.rollback()
        raise self.retry(exc=exc, countdown=60)

    finally:
        db.close()
