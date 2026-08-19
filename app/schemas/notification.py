"""
app/schemas/notification.py

Module 04 — Async Notification Pipeline: internal Pydantic models.

These schemas are used as Celery task arguments (serialised to JSON via Redis)
and as structured log entries for the escalation audit trail.

Design note:
  Celery serialises task arguments as JSON. Using Pydantic models here gives us
  type-safe construction in tasks.py and easy .model_dump() for serialisation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NotificationPayload(BaseModel):
    """
    Serialisable argument for the send_notification_task Celery task.

    channel     — 'sms' | 'email' | 'both'
    recipient   — phone number (E.164 for SMS) or email address
    subject     — email subject line (ignored for SMS)
    body        — plain-text body
    html_body   — HTML email body (optional; falls back to body if None)
    report_id   — for traceability in logs
    """
    channel: Literal["sms", "email", "both"] = "both"
    recipient_phone: str | None = None
    recipient_email: str | None = None
    subject: str = Field(default="MediSync Notification")
    body: str
    html_body: str | None = None
    report_id: str | None = None
    doctor_id: str | None = None


class EscalationEvent(BaseModel):
    """
    Structured log record written each time an escalation fires.
    Stored in the doctor_notes field of the expired CaseAssignment row.
    """
    event_type: Literal["offered", "expired", "escalated", "max_escalations_reached"]
    assignment_id: str
    report_id: str
    doctor_id: str
    escalation_count: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str
