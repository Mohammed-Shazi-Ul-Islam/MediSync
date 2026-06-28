import uuid
from datetime import datetime, timezone

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.user import User, UserRole

settings = get_settings()

# ── Password Hashing ───────────────────────────────────────────────────────────
# bcrypt is the industry standard for password hashing.
# passlib handles the salt automatically — never hash passwords manually.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


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
    Also returns expiry datetime for storage in DB (enables server-side revocation).
    """
    to_encode = data.copy()
    expires_at = datetime.now(timezone.utc)
    expire_ts = expires_at.timestamp() + (settings.refresh_token_expire_days * 86400)
    to_encode.update({"exp": expire_ts, "type": "refresh"})
    token = jwt.encode(to_encode, settings.secret_key, algorithm=settings.algorithm)

    # Return the naive UTC datetime for DB storage
    expires_at_naive = datetime.utcfromtimestamp(expire_ts)
    return token, expires_at_naive


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


def login_user(
    db: Session, email: str, password: str
) -> tuple[str, str, datetime]:
    """
    Authenticate credentials and return (access_token, refresh_token, refresh_expires_at).
    Stores the refresh token in DB for revocation capability.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        raise ValueError("Invalid email or password")

    if not user.is_active:
        raise ValueError("This account has been deactivated. Contact support.")

    token_data = {"sub": str(user.id), "role": user.role.value}
    access_token = create_access_token(token_data)
    refresh_token, refresh_expires = create_refresh_token(token_data)

    # Persist refresh token for server-side revocation
    user.refresh_token = refresh_token
    user.refresh_token_expires_at = refresh_expires
    db.commit()

    return access_token, refresh_token, refresh_expires


def refresh_access_token(
    db: Session, refresh_token: str
) -> tuple[str, str, datetime]:
    """
    Validate refresh token, issue new access + refresh token pair (rotation).
    Token rotation: every refresh invalidates the old refresh token.
    This limits the damage window if a refresh token is stolen.
    """
    payload = decode_token(refresh_token)

    if payload.get("type") != "refresh":
        raise ValueError("Invalid token type — expected refresh token")

    user_id = payload.get("sub")
    user = db.query(User).filter(User.id == uuid.UUID(user_id)).first()

    if not user:
        raise ValueError("User not found")

    if user.refresh_token != refresh_token:
        raise ValueError("Refresh token has been revoked or rotated")

    if user.refresh_token_expires_at < datetime.utcnow():
        raise ValueError("Refresh token has expired. Please log in again.")

    # Issue new token pair (rotation)
    token_data = {"sub": str(user.id), "role": user.role.value}
    new_access_token = create_access_token(token_data)
    new_refresh_token, new_refresh_expires = create_refresh_token(token_data)

    user.refresh_token = new_refresh_token
    user.refresh_token_expires_at = new_refresh_expires
    db.commit()

    return new_access_token, new_refresh_token, new_refresh_expires


def logout_user(db: Session, user: User) -> None:
    """Invalidate the user's refresh token, forcing re-authentication."""
    user.refresh_token = None
    user.refresh_token_expires_at = None
    db.commit()
