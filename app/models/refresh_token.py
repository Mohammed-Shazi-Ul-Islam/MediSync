"""
app/models/refresh_token.py

Module 06 — Dedicated refresh-token table.

Replaces the inline `refresh_token` / `refresh_token_expires_at` columns
that were previously stored directly on the User row.

Advantages over the old approach:
  - Multi-device: each device gets its own row → selective revocation.
  - Security: we store a SHA-256 *hash* of the JWT, not the raw token.
    Even if the DB is exfiltrated, tokens cannot be replayed without the
    original value (which the client holds).
  - Revocation audit: `revoked_at` tells us when and (via join) who revoked it.
  - Token family: token rotation writes a new row and sets `revoked_at` on the
    old one — replay detection is trivial (revoked_at IS NOT NULL).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Base):
    """
    One row per issued refresh token.

    Lifecycle:
      issued  → revoked_at IS NULL, expires_at in future  (valid)
      rotated → revoked_at IS NOT NULL                     (old token)
      expired → expires_at < now()                          (stale, can be purged)
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )

    # ── Ownership ──────────────────────────────────────────────────────────────
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Token identity ─────────────────────────────────────────────────────────
    # SHA-256 hex digest of the raw JWT string.
    # Indexed for fast lookup on refresh; unique ensures no duplicate issuance.
    token_hash: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )

    # ── Device context (optional UX hint, never security-critical) ────────────
    device_hint: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Expiry & revocation ───────────────────────────────────────────────────
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Set when the token is rotated (refresh) or explicitly revoked (logout).
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped[User] = relationship("User", back_populates="refresh_tokens")
