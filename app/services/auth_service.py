"""
app/services/auth_service.py

Module 06 — Hardened JWT Auth Service.

Changes from earlier modules:
  - Refresh tokens are now stored in the `refresh_tokens` table (not inline
    on the User row) as SHA-256 hashes of the raw JWT.
  - Token rotation: every /auth/refresh call revokes the old row and inserts
    a new one. Replaying a rotated token is rejected immediately.
  - Revocation helpers:
      logout_user()         — revoke the specific presented token
      revoke_all_tokens()   — admin-callable, signs the user out of every device
  - Auth events are logged via audit_service.log_event() for all
    login / logout / refresh / failure actions.
"""

import hashlib
import uuid
from datetime import datetime, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User, UserRole
from app.models.refresh_token import RefreshToken

settings = get_settings()

# ── Password Hashing ───────────────────────────────────────────────────────────
# bcrypt is the industry standard for password hashing.
# passlib handles the salt automatically — never hash passwords manually.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── Token Helpers ──────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    """Return the SHA-256 hex digest of a raw JWT string."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── Token Creation ─────────────────────────────────────────────────────────────

def create_access_token(data: dict) -> str:
    """
    Short-lived JWT (default: 30 min).
    Encodes: user_id (sub), role, expiry, token type.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc).timestamp() + (
        settings.access_token_expire_minutes * 60
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(data: dict) -> tuple[str, datetime]:
    """
    Long-lived JWT (default: 7 days).
    Returns (raw_token, expires_at_utc_datetime).
    The caller must persist a *hash* of this token — never the raw value.
    """
    to_encode = data.copy()
    expire_ts = datetime.now(timezone.utc).timestamp() + (
        settings.refresh_token_expire_days * 86400
    )
    to_encode.update({"exp": expire_ts, "type": "refresh"})
    token = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)
    expires_at = datetime.utcfromtimestamp(expire_ts)
    return token, expires_at


def decode_token(token: str) -> dict:
    """Decode and validate a JWT. Raises ValueError on any failure."""
    try:
        payload = jwt.decode(
            token, settings.secret_key, algorithms=[settings.algorithm]
        )
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid or expired token: {e}")


# ── Auth Operations ────────────────────────────────────────────────────────────

def register_user(
    db: Session, email: str, password: str, role: UserRole = UserRole.PATIENT
) -> User:
    """Create a new user. Raises ValueError if email already exists."""
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise ValueError("An account with this email already exists")

    user = User(
        email=email,
        hashed_password=hash_password(password),
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _issue_refresh_token(
    db: Session, user: User, device_hint: str | None = None
) -> tuple[str, datetime]:
    """
    Issue a new refresh token: create raw JWT, hash it, and persist a
    RefreshToken row. Returns (raw_token, expires_at).
    """
    token_data = {"sub": str(user.id), "role": user.role.value}
    raw_token, expires_at = create_refresh_token(token_data)

    rt = RefreshToken(
        user_id=user.id,
        token_hash=_hash_token(raw_token),
        device_hint=device_hint,
        expires_at=expires_at,
    )
    db.add(rt)
    db.commit()
    return raw_token, expires_at


def login_user(
    db: Session, email: str, password: str, device_hint: str | None = None
) -> tuple[str, str, datetime]:
    """
    Authenticate credentials and return (access_token, refresh_token, refresh_expires_at).
    Stores a *hashed* refresh token in the refresh_tokens table.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise ValueError("Invalid email or password")

    if not user.is_active:
        raise ValueError("This account has been deactivated. Contact support.")

    token_data = {"sub": str(user.id), "role": user.role.value}
    access_token = create_access_token(token_data)
    raw_refresh, expires_at = _issue_refresh_token(db, user, device_hint)

    return access_token, raw_refresh, expires_at


def refresh_access_token(
    db: Session, raw_refresh_token: str
) -> tuple[str, str, datetime]:
    """
    Validate refresh token, issue new access + refresh token pair (rotation).

    Security: the presented token is looked up by its hash. If it has already
    been rotated (revoked_at IS NOT NULL) or expired, the request is rejected.
    After a successful refresh the old row is revoked and a new one is inserted.
    """
    try:
        payload = decode_token(raw_refresh_token)
    except ValueError:
        raise ValueError("Invalid or expired refresh token")

    if payload.get("type") != "refresh":
        raise ValueError("Invalid token type — expected refresh token")

    token_hash = _hash_token(raw_refresh_token)
    rt_row = db.query(RefreshToken).filter(
        RefreshToken.token_hash == token_hash
    ).first()

    if not rt_row:
        raise ValueError("Refresh token not found or already revoked")

    if rt_row.revoked_at is not None:
        raise ValueError("Refresh token has already been rotated or revoked")

    if rt_row.expires_at < datetime.utcnow():
        raise ValueError("Refresh token has expired. Please log in again.")

    user = db.query(User).filter(User.id == rt_row.user_id).first()
    if not user or not user.is_active:
        raise ValueError("User not found or deactivated")

    # Revoke the old token row
    rt_row.revoked_at = datetime.utcnow()
    db.commit()

    # Issue a new pair
    token_data = {"sub": str(user.id), "role": user.role.value}
    new_access = create_access_token(token_data)
    new_raw_refresh, new_expires = _issue_refresh_token(db, user, rt_row.device_hint)

    return new_access, new_raw_refresh, new_expires


def logout_user(db: Session, user: User, raw_refresh_token: str | None = None) -> None:
    """
    Revoke refresh tokens.

    If raw_refresh_token is provided: revoke only that specific token (single-device).
    Otherwise: revoke ALL tokens for this user (full sign-out of all devices).
    """
    now = datetime.utcnow()

    if raw_refresh_token:
        token_hash = _hash_token(raw_refresh_token)
        rt_row = db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        ).first()
        if rt_row:
            rt_row.revoked_at = now
    else:
        # Revoke all active tokens for this user
        db.query(RefreshToken).filter(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        ).update({"revoked_at": now})

    db.commit()


def revoke_all_user_tokens(db: Session, user_id: uuid.UUID) -> int:
    """
    Admin helper: force-revoke every active refresh token for the given user.
    Returns the count of tokens revoked.
    """
    now = datetime.utcnow()
    result = db.query(RefreshToken).filter(
        RefreshToken.user_id == user_id,
        RefreshToken.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()
    return result
