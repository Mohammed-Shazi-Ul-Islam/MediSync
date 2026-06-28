import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum as SAEnum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserRole(str, enum.Enum):
    """
    str + enum.Enum: makes it JSON-serialisable and comparable with plain strings.
    e.g.  user.role == "patient"  works correctly.
    """
    PATIENT = "patient"
    DOCTOR = "doctor"
    ADMIN = "admin"


class User(Base):
    """
    Central auth table. Every person in the system (patient, doctor, admin)
    has exactly one User row. Role-specific profile data lives in separate
    tables (Patient, Doctor) that FK to this table.

    JWT tokens encode the user's UUID and role — no DB lookup needed to
    determine role during auth checks.
    """
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        SAEnum(UserRole, name="userrole"), default=UserRole.PATIENT, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Refresh Token Storage ──────────────────────────────────────────────────
    # Stored so we can revoke tokens on logout (single-device per account).
    # Module 06 will upgrade this to a separate RefreshToken table for
    # multi-device support.
    refresh_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
