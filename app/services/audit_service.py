"""
app/services/audit_service.py

Module 06 — Centralised audit logging service.

Single entry point: log_event()

Design principles:
  - Non-fatal: any DB write failure is caught, logged to stderr, and the
    request continues. The audit log should never crash production traffic.
  - Self-contained: each row captures enough context (actor_role, payload
    snapshot) to be meaningful even if the source rows are later mutated.
  - HTTP-aware: when a FastAPI Request object is passed, the client IP and
    User-Agent are extracted automatically from headers.
  - Celery-safe: can be called without a Request object (actor/ip = None).

Usage:
    from app.services.audit_service import log_event
    from app.models.audit_log import AuditEventType

    # From a route handler
    log_event(
        db=db,
        event_type=AuditEventType.CASE_ACCEPTED,
        resource_type="case_assignment",
        resource_id=assignment.id,
        actor=current_user,
        payload={"notes": body.notes, "doctor_id": str(doc.id)},
        request=request,
    )

    # From a Celery task (no HTTP request context)
    log_event(
        db=db,
        event_type=AuditEventType.TRIAGE_COMPLETED,
        resource_type="symptom_report",
        resource_id=report.id,
        payload={"urgency_level": result.urgency_level},
    )
"""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog, AuditEventType
from app.models.user import User

logger = logging.getLogger(__name__)


def _extract_ip(request: Any) -> str | None:
    """
    Extract the real client IP from a FastAPI Request.
    Respects X-Forwarded-For (set by reverse proxies / load balancers).
    """
    if request is None:
        return None
    try:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        if request.client:
            return request.client.host
    except Exception:
        pass
    return None


def _extract_user_agent(request: Any) -> str | None:
    if request is None:
        return None
    try:
        return request.headers.get("user-agent")
    except Exception:
        return None


def log_event(
    db: Session,
    event_type: AuditEventType,
    resource_type: str | None = None,
    resource_id: uuid.UUID | str | None = None,
    actor: User | None = None,
    payload: dict | None = None,
    request: Any = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AuditLog | None:
    """
    Write one immutable row to the audit_log table.

    Parameters
    ----------
    db           : SQLAlchemy Session (sync, from get_db() or Celery task).
    event_type   : AuditEventType enum value.
    resource_type: Human-readable type string, e.g. "symptom_report".
    resource_id  : UUID of the affected object.
    actor        : Authenticated User who triggered the event (None for system events).
    payload      : Arbitrary dict snapshot to persist alongside the event.
    request      : FastAPI Request — if provided, IP + User-Agent are extracted.
    ip_address   : Override IP when request is not available.
    user_agent   : Override User-Agent when request is not available.

    Returns the created AuditLog row, or None if the write failed.
    """
    try:
        # Resolve IP / UA from request if not explicitly provided
        resolved_ip = ip_address or _extract_ip(request)
        resolved_ua = user_agent or _extract_user_agent(request)

        # Normalise resource_id to string for storage
        resource_id_str: str | None = None
        if resource_id is not None:
            resource_id_str = str(resource_id)

        entry = AuditLog(
            event_type=event_type,
            actor_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            resource_type=resource_type,
            resource_id=resource_id_str,
            payload=payload,
            ip_address=resolved_ip,
            user_agent=resolved_ua,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    except Exception as exc:
        # Non-fatal: log the failure but never crash the caller.
        logger.error(
            "[audit_service] Failed to write audit log entry: %s | "
            "event_type=%s resource_type=%s resource_id=%s actor=%s",
            exc,
            event_type,
            resource_type,
            resource_id,
            actor.id if actor else None,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return None
