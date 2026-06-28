"""
app/utils/dependencies.py

FastAPI dependency functions for authentication and authorization.

These are injected into route functions via Depends():
    current_user: User = Depends(get_current_user)
    admin_user:   User = Depends(require_role(UserRole.ADMIN))

Design note:
    - get_current_user validates the JWT and fetches the user from DB.
    - require_role is a factory that returns a dependency, allowing
      any combination of roles: require_role(UserRole.DOCTOR, UserRole.ADMIN)
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserRole
from app.services.auth_service import decode_token

# HTTPBearer extracts the token from the Authorization: Bearer <token> header.
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """
    Core authentication dependency.
    Validates the JWT access token and returns the corresponding User object.
    Raises HTTP 401 if the token is invalid, expired, or the user is inactive.
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Expected an access token, got something else",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is missing user ID",
        )

    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User associated with this token no longer exists",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    return user


def require_role(*roles: UserRole):
    """
    Role-based access control factory.

    Usage:
        @router.get("/admin-only")
        def admin_endpoint(user: User = Depends(require_role(UserRole.ADMIN))):
            ...

        @router.get("/doctor-or-admin")
        def mixed_endpoint(user: User = Depends(require_role(UserRole.DOCTOR, UserRole.ADMIN))):
            ...
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied. This endpoint requires one of: "
                    f"{[r.value for r in roles]}"
                ),
            )
        return current_user

    return role_checker
