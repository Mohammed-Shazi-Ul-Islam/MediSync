"""
app/api/v1/routes/admin.py

Module 06 — Admin REST API.

All endpoints require role=admin (enforced via require_role(UserRole.ADMIN)).

Route map:
  GET    /admin/users                    → list_users
  GET    /admin/users/{id}               → get_user
  PATCH  /admin/users/{id}/role          → change_user_role
  PATCH  /admin/users/{id}/activate      → set_user_activation
  DELETE /admin/users/{id}/tokens        → force_logout_user
  GET    /admin/audit-log                → query_audit_log
  GET    /admin/audit-log/{id}           → get_audit_entry
  GET    /admin/rate-limit/stats         → get_rate_limit_stats
"""

import uuid
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.rate_limiter import limiter, LIMIT_ADMIN
from app.models.audit_log import AuditLog, AuditEventType
from app.models.user import User, UserRole
from app.schemas.admin import (
    AuditLogListResponse,
    AuditLogRead,
    RateLimitStats,
    UserActivationUpdate,
    UserAdminListResponse,
    UserAdminRead,
    UserRoleUpdate,
)
from app.services import audit_service
from app.services.auth_service import revoke_all_user_tokens
from app.utils.dependencies import require_role
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/admin", tags=["Admin"])


# ── User Management ────────────────────────────────────────────────────────────

@router.get(
    "/users",
    response_model=UserAdminListResponse,
    summary="List all users (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def list_users(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    role: Optional[UserRole] = Query(default=None, description="Filter by role"),
    is_active: Optional[bool] = Query(default=None, description="Filter by activation status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Paginated list of all users. Filterable by role and active status.
    """
    query = db.query(User)
    if role is not None:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()

    return UserAdminListResponse(total=total, page=page, limit=limit, items=items)


@router.get(
    "/users/{user_id}",
    response_model=UserAdminRead,
    summary="Get any user by ID (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def get_user(
    request: Request,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Retrieve full user record by UUID."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch(
    "/users/{user_id}/role",
    response_model=UserAdminRead,
    summary="Change user role (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def change_user_role(
    request: Request,
    user_id: uuid.UUID,
    body: UserRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Change a user's role. Emits an ADMIN_ROLE_CHANGED audit event.
    The user's next login will issue a token reflecting the new role.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_role = user.role.value
    user.role = body.role
    db.commit()
    db.refresh(user)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.ADMIN_ROLE_CHANGED,
        resource_type="user",
        resource_id=user.id,
        actor=current_user,
        payload={"old_role": old_role, "new_role": body.role.value},
        request=request,
    )

    return user


@router.patch(
    "/users/{user_id}/activate",
    response_model=UserAdminRead,
    summary="Activate or deactivate a user account (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def set_user_activation(
    request: Request,
    user_id: uuid.UUID,
    body: UserActivationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Set a user's active status. Deactivated users cannot log in and their
    existing access tokens will be rejected by get_current_user().
    Emits an ADMIN_ACCOUNT_ACTIVATED audit event.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    old_status = user.is_active
    user.is_active = body.is_active
    db.commit()
    db.refresh(user)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.ADMIN_ACCOUNT_ACTIVATED,
        resource_type="user",
        resource_id=user.id,
        actor=current_user,
        payload={"old_is_active": old_status, "new_is_active": body.is_active},
        request=request,
    )

    return user


@router.delete(
    "/users/{user_id}/tokens",
    status_code=status.HTTP_200_OK,
    summary="Force-revoke all refresh tokens (admin sign-out)",
)
@limiter.limit(LIMIT_ADMIN)
def force_logout_user(
    request: Request,
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Revoke all active refresh tokens for a user, effectively signing them out
    of every device. Their current access tokens will expire naturally.
    Emits an ADMIN_TOKENS_REVOKED audit event.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    revoked_count = revoke_all_user_tokens(db, user_id)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.ADMIN_TOKENS_REVOKED,
        resource_type="user",
        resource_id=user.id,
        actor=current_user,
        payload={"revoked_token_count": revoked_count},
        request=request,
    )

    return {"message": f"Revoked {revoked_count} active refresh token(s) for user {user_id}."}


# ── Audit Log ──────────────────────────────────────────────────────────────────

@router.get(
    "/audit-log",
    response_model=AuditLogListResponse,
    summary="Query audit log (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def query_audit_log(
    request: Request,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    event_type: Optional[AuditEventType] = Query(default=None),
    actor_id: Optional[uuid.UUID] = Query(default=None),
    resource_type: Optional[str] = Query(default=None),
    resource_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Paginated, filterable audit log query.

    Filter combinations:
      - event_type: specific event category
      - actor_id: everything a specific user did
      - resource_type + resource_id: full history of a specific record
    """
    q = db.query(AuditLog)

    if event_type:
        q = q.filter(AuditLog.event_type == event_type)
    if actor_id:
        q = q.filter(AuditLog.actor_id == actor_id)
    if resource_type:
        q = q.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        q = q.filter(AuditLog.resource_id == str(resource_id))

    q = q.order_by(AuditLog.created_at.desc())
    total = q.count()
    items = q.offset((page - 1) * limit).limit(limit).all()

    return AuditLogListResponse(total=total, page=page, limit=limit, items=items)


@router.get(
    "/audit-log/{entry_id}",
    response_model=AuditLogRead,
    summary="Get a single audit log entry (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def get_audit_entry(
    request: Request,
    entry_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """Retrieve a single audit log entry by its UUID."""
    entry = db.query(AuditLog).filter(AuditLog.id == entry_id).first()
    if not entry:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Audit log entry not found"
        )
    return entry


# ── Rate Limit Stats ───────────────────────────────────────────────────────────

@router.get(
    "/rate-limit/stats",
    response_model=RateLimitStats,
    summary="View current rate-limit configuration (admin)",
)
@limiter.limit(LIMIT_ADMIN)
def get_rate_limit_stats(
    request: Request,
    current_user: User = Depends(require_role(UserRole.ADMIN)),
):
    """
    Returns the current rate-limit configuration.
    Note: live counter values require Redis SCAN — this endpoint returns
    the configured limits only. For real-time counters, query Redis directly.
    """
    from app.middleware.rate_limiter import limiter as _limiter

    storage_type = type(_limiter._storage).__name__ if hasattr(_limiter, "_storage") else "unknown"

    return RateLimitStats(
        storage_type=storage_type,
        rate_limit_enabled=settings.rate_limit_enabled,
        limits={
            "global_per_minute": f"{settings.rate_limit_global_per_minute}/min (per IP)",
            "auth_per_minute":   f"{settings.rate_limit_auth_per_minute}/min (per IP)",
            "intake_per_minute": f"{settings.rate_limit_intake_per_minute}/min (per user)",
            "admin_per_minute":  f"{settings.rate_limit_admin_per_minute}/min (per user)",
        },
    )
