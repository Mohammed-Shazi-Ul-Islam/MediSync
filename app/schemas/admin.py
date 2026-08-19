"""
app/schemas/admin.py

Module 06 — Admin API request/response schemas.

These Pydantic models are used exclusively by the /admin/* endpoints.
They intentionally expose more internal fields than the patient/doctor-facing
schemas to give admins full visibility.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr

from app.models.audit_log import AuditEventType
from app.models.user import UserRole


# ── User Admin Schemas ─────────────────────────────────────────────────────────

class UserAdminRead(BaseModel):
    """Full user record as visible to an admin."""
    id: uuid.UUID
    email: str
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserRoleUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}/role"""
    role: UserRole


class UserActivationUpdate(BaseModel):
    """Body for PATCH /admin/users/{id}/activate"""
    is_active: bool


class UserAdminListResponse(BaseModel):
    """Paginated list of users."""
    total: int
    page: int
    limit: int
    items: list[UserAdminRead]


# ── Audit Log Schemas ──────────────────────────────────────────────────────────

class AuditLogRead(BaseModel):
    """Single audit log entry as returned by the API."""
    id: uuid.UUID
    event_type: AuditEventType
    actor_id: uuid.UUID | None
    actor_role: str | None
    resource_type: str | None
    resource_id: str | None
    payload: dict[str, Any] | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    """Paginated list of audit log entries."""
    total: int
    page: int
    limit: int
    items: list[AuditLogRead]


# ── Rate Limit Stats Schema ────────────────────────────────────────────────────

class RateLimitStats(BaseModel):
    """Current rate-limit storage stats (Redis or in-memory)."""
    storage_type: str
    rate_limit_enabled: bool
    limits: dict[str, str]
