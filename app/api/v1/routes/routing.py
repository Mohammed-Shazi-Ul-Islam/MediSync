"""
app/api/v1/routes/routing.py

Module 03 — Specialist Router: REST API endpoints.

Exposes:
  POST /api/v1/routing/decide
    → Accept a TriageResult payload or a report_id, run the HybridSpecialistRouter,
      return a RoutingDecision. Requires authentication.

  GET  /api/v1/routing/specialists
    → Return the full catalogue of supported specialist types with display names
      and descriptions. Useful for frontend dropdowns and mobile apps. No auth.

  GET  /api/v1/routing/reports/{report_id}/decision
    → Retrieve the stored RoutingDecision for a specific SymptomReport from the DB.
      Returns 404 if the report hasn't been routed yet.

Design notes:
  - POST /decide accepts both inline payloads and DB lookups — callers choose
    whichever is more convenient (inline for testing, report_id for production).
  - GET /specialists is intentionally unauthenticated so a patient-facing app
    can populate specialist dropdowns before login.
  - All Pydantic validation errors are automatically converted to 422 by FastAPI.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.intake import SymptomReport
from app.schemas.routing import (
    SPECIALIST_DESCRIPTIONS,
    SPECIALIST_DISPLAY_NAMES,
    RoutingDecision,
    RoutingRequest,
    SpecialistInfo,
    SpecialistType,
)
from app.schemas.triage import TriageResult
from app.utils.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/routing", tags=["Module 03 — Specialist Router"])


# ── POST /routing/decide ───────────────────────────────────────────────────────

@router.post(
    "/decide",
    response_model=RoutingDecision,
    status_code=status.HTTP_200_OK,
    summary="Route symptoms to a specialist",
    description=(
        "Run the hybrid Rule + AI specialist routing engine on a TriageResult. "
        "Supply either an inline `triage_result` payload or a `report_id` from a "
        "previously submitted symptom report. "
        "Returns a `RoutingDecision` with the recommended specialist, confidence score, "
        "routing method, reasoning, and alternative options."
    ),
    responses={
        200: {"description": "Routing decision computed successfully"},
        400: {"description": "Neither triage_result nor report_id was provided"},
        404: {"description": "Report ID not found or AI analysis not yet available"},
        503: {"description": "Routing service temporarily unavailable (embedding API down)"},
    },
)
def route_to_specialist(
    request: RoutingRequest,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> RoutingDecision:
    """
    Main routing endpoint.

    Decision precedence:
      1. If `triage_result` is provided in the request body, use it directly.
      2. Else look up the report by `report_id` and use its stored `ai_analysis`.
      3. Run HybridSpecialistRouter.route() and return the RoutingDecision.
    """
    from app.services.specialist_router import hybrid_router

    # ── Resolve TriageResult ───────────────────────────────────────────────────
    if request.triage_result is not None:
        triage_result = request.triage_result
        logger.info("[ROUTING] Using inline TriageResult from request body")

    elif request.report_id is not None:
        # Load from DB
        try:
            report_uuid = uuid.UUID(request.report_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid report_id format: '{request.report_id}'. Must be a valid UUID.",
            )

        report = db.query(SymptomReport).filter(SymptomReport.id == report_uuid).first()
        if not report:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"SymptomReport '{request.report_id}' not found.",
            )

        if not report.ai_analysis:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"Report '{request.report_id}' has not been triaged yet "
                    f"(status: {report.status}). Wait for AI analysis to complete."
                ),
            )

        # Deserialise stored JSONB → TriageResult
        try:
            triage_result = TriageResult.model_validate(report.ai_analysis)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to parse stored triage analysis: {e}",
            )

        logger.info(f"[ROUTING] Loaded TriageResult from report {request.report_id}")

    else:
        # This should be caught by Pydantic validator but guard here too
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either 'triage_result' or 'report_id' in the request body.",
        )

    # ── Run Routing ────────────────────────────────────────────────────────────
    try:
        decision = hybrid_router.route(triage_result)
    except RuntimeError as e:
        # e.g. GEMINI_API_KEY not set
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Specialist routing service unavailable: {e}",
        )
    except Exception as e:
        logger.error(f"[ROUTING] Unexpected error in hybrid_router.route(): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during specialist routing.",
        )

    logger.info(
        f"[ROUTING] ✓ Decision: specialist={decision.specialist}, "
        f"confidence={decision.confidence}, method={decision.routing_method}"
    )
    return decision


# ── GET /routing/specialists ───────────────────────────────────────────────────

@router.get(
    "/specialists",
    response_model=list[SpecialistInfo],
    status_code=status.HTTP_200_OK,
    summary="List all supported specialist types",
    description=(
        "Returns the full catalogue of specialist types supported by the MediSync routing engine. "
        "Includes canonical code, display name, and a brief description of each specialty. "
        "No authentication required — safe for public frontend use."
    ),
)
def list_specialists() -> list[SpecialistInfo]:
    """
    Return all specialist types with display names and descriptions.
    Useful for populating dropdowns, reference tables, and documentation.
    """
    return [
        SpecialistInfo(
            code=sp.value,
            display_name=SPECIALIST_DISPLAY_NAMES[sp.value],
            description=SPECIALIST_DESCRIPTIONS[sp.value],
        )
        for sp in SpecialistType
    ]


# ── GET /routing/reports/{report_id}/decision ─────────────────────────────────

@router.get(
    "/reports/{report_id}/decision",
    response_model=RoutingDecision,
    status_code=status.HTTP_200_OK,
    summary="Get stored routing decision for a report",
    description=(
        "Retrieve the stored RoutingDecision for a specific SymptomReport. "
        "This returns the decision that was computed by the Celery worker after "
        "the AI triage pipeline completed. Returns 404 if routing hasn't run yet."
    ),
    responses={
        200: {"description": "Routing decision found"},
        404: {"description": "Report not found or routing decision not yet available"},
    },
)
def get_report_routing_decision(
    report_id: str,
    db: Session = Depends(get_db),
    _current_user=Depends(get_current_user),
) -> RoutingDecision:
    """Return the stored RoutingDecision from symptom_reports.routing_decision JSONB."""
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid report_id format: '{report_id}'. Must be a valid UUID.",
        )

    report = db.query(SymptomReport).filter(SymptomReport.id == report_uuid).first()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"SymptomReport '{report_id}' not found.",
        )

    if not report.routing_decision:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Routing decision not yet available for report '{report_id}'. "
                f"Current status: {report.status}. Wait for the async pipeline to complete."
            ),
        )

    try:
        return RoutingDecision.model_validate(report.routing_decision)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to parse stored routing decision: {e}",
        )
