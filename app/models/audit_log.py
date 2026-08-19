"""
app/models/audit_log.py

Module 06 — Immutable audit log table.

One row per audited event across the entire MediSync pipeline:
  - AI triage decisions
  - Case accept / reject / escalation
  - Admin actions (role changes, deactivations)
  - Auth events (login, logout, failed attempts)
  - Rate-limit violations

Design principles:
  - No `updated_at` — rows are IMMUTABLE once written.
  - `payload` JSONB stores a full snapshot so the log is self-contained even
    if the source row is later mutated or deleted.
  - `actor_id` is nullable to accommodate system-generated events (e.g. Celery
    escalation tasks that run without a human actor).
  - `ip_address` / `user_agent` are captured at write-time from the HTTP request
    for forensic traceability.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditEventType(str, enum.Enum):
    """
    Enumeration of all auditable event categories.
    Keep this list append-only — never rename or remove values.
    """
    # AI pipeline events
    TRIAGE_COMPLETED   = "triage_completed"
    ROUTING_COMPLETED  = "routing_completed"

    # Case lifecycle events
    CASE_ACCEPTED      = "case_accepted"
    CASE_REJECTED      = "case_rejected"
    CASE_ESCALATED     = "case_escalated"
    CASE_CLOSED        = "case_closed"

    # Admin actions
    ADMIN_USER_CREATED      = "admin_user_created"
    ADMIN_ROLE_CHANGED      = "admin_role_changed"
    ADMIN_ACCOUNT_ACTIVATED = "admin_account_activated"
    ADMIN_TOKENS_REVOKED    = "admin_tokens_revoked"

    # Auth events
    AUTH_LOGIN         = "auth_login"
    AUTH_LOGOUT        = "auth_logout"
    AUTH_REFRESH       = "auth_refresh"
    AUTH_LOGIN_FAILED  = "auth_login_failed"

    # Abuse / rate limiting
    RATE_LIMITED       = "rate_limited"


class AuditLog(Base):
    """
    Append-only audit log. Written by audit_service.log_event().
    Never updated or deleted in application code.

    Indexed for the two most common admin query patterns:
      1. "Show me everything that happened to report X"
         → index on (resource_type, resource_id)
      2. "Show me everything actor Y did in the last 7 days"
         → index on (actor_id, created_at)
    """
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )

    # ── Event classification ───────────────────────────────────────────────────
    event_type: Mapped[AuditEventType] = mapped_column(
        SAEnum(AuditEventType, name="auditeventtype"),
        nullable=False,
        index=True,
    )

    # ── Actor (who triggered the event) ───────────────────────────────────────
    # Nullable: system/Celery events have no human actor.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Captured at write-time so role changes don't rewrite history.
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ── Affected resource ─────────────────────────────────────────────────────
    resource_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        # Store as string for SQLite test compatibility; PG casts automatically.
        String(36), nullable=True, index=True
    )

    # ── Full event snapshot ───────────────────────────────────────────────────
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── HTTP request context (forensics) ──────────────────────────────────────
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Immutable timestamp ────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    actor: Mapped[User | None] = relationship("User", foreign_keys=[actor_id])
