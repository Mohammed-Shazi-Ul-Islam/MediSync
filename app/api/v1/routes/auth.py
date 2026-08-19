"""
app/api/v1/routes/auth.py

Module 06 updates:
  - Rate limiting applied to login and refresh endpoints (brute-force protection).
  - AUTH_EVENT audit log entries written for login, logout, and failed auth.
  - logout now accepts an optional refresh_token body to do single-device sign-out.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.middleware.rate_limiter import limiter, LIMIT_AUTH
from app.models.audit_log import AuditEventType
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import audit_service
from app.services.auth_service import (
    login_user,
    logout_user,
    refresh_access_token,
    register_user,
)
from app.utils.dependencies import get_current_user
from app.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
def register(request: Request, data: RegisterRequest, db: Session = Depends(get_db)):
    """
    Create a new user (patient, doctor, or admin).
    After registration, use POST /auth/login to obtain tokens.
    """
    try:
        user = register_user(db, data.email, data.password, data.role)
        return user
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and obtain JWT tokens",
)
@limiter.limit(LIMIT_AUTH)
def login(request: Request, data: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with email + password.
    Returns an access token (short-lived) and refresh token (long-lived).
    Include the access token in subsequent requests:
        Authorization: Bearer <access_token>

    Rate limited: 10 requests / minute per IP.
    """
    user_agent = request.headers.get("user-agent")
    try:
        access_token, refresh_token, _ = login_user(
            db, data.email, data.password, device_hint=user_agent
        )
        # Fetch user for audit log (login_user doesn't return User object directly)
        from app.models.user import User as UserModel
        user = db.query(UserModel).filter(UserModel.email == data.email).first()
        audit_service.log_event(
            db=db,
            event_type=AuditEventType.AUTH_LOGIN,
            resource_type="user",
            resource_id=user.id if user else None,
            actor=user,
            payload={"email": data.email},
            request=request,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except ValueError as e:
        # Log failed login attempts (no actor since auth failed)
        audit_service.log_event(
            db=db,
            event_type=AuditEventType.AUTH_LOGIN_FAILED,
            resource_type="user",
            payload={"email": data.email, "reason": str(e)},
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
@limiter.limit(LIMIT_AUTH)
def refresh(request: Request, data: RefreshRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    Token rotation: the old refresh token is invalidated immediately.

    Rate limited: 10 requests / minute per IP.
    """
    try:
        access_token, new_refresh_token, _ = refresh_access_token(
            db, data.refresh_token
        )
        audit_service.log_event(
            db=db,
            event_type=AuditEventType.AUTH_REFRESH,
            resource_type="refresh_token",
            payload={"rotated": True},
            request=request,
        )
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout and invalidate tokens",
)
def logout(
    request: Request,
    data: RefreshRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Revoke refresh token(s) to sign out.

    - If a `refresh_token` body is provided: only that token is revoked (single-device logout).
    - If omitted or body is empty: all active refresh tokens for the user are revoked
      (sign out all devices).

    Access tokens will expire naturally within the configured window (default: 30 min).
    """
    raw_token = data.refresh_token if data else None
    logout_user(db, current_user, raw_refresh_token=raw_token)

    audit_service.log_event(
        db=db,
        event_type=AuditEventType.AUTH_LOGOUT,
        resource_type="user",
        resource_id=current_user.id,
        actor=current_user,
        payload={"single_device": raw_token is not None},
        request=request,
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the profile of the currently authenticated user."""
    return current_user
