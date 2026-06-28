from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
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
def register(data: RegisterRequest, db: Session = Depends(get_db)):
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
def login(data: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with email + password.
    Returns an access token (short-lived) and refresh token (long-lived).
    Include the access token in subsequent requests:
        Authorization: Bearer <access_token>
    """
    try:
        access_token, refresh_token, _ = login_user(db, data.email, data.password)
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.access_token_expire_minutes * 60,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    """
    Exchange a valid refresh token for a new access + refresh token pair.
    Token rotation: the old refresh token is invalidated immediately.
    """
    try:
        access_token, new_refresh_token, _ = refresh_access_token(
            db, data.refresh_token
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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Invalidate the current user's refresh token.
    The access token will expire naturally (within 30 min).
    """
    logout_user(db, current_user)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user",
)
def get_me(current_user: User = Depends(get_current_user)):
    """Returns the profile of the currently authenticated user."""
    return current_user
