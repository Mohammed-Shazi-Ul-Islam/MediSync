"""
alembic/versions/003_add_audit_log_and_refresh_tokens.py

Module 06 — Admin + Audit Layer: DB migration.

Creates:
  - refresh_tokens table (replaces inline refresh_token columns on users)
  - audit_log table (immutable event log for triage, admin, auth events)

Modifies:
  - users: drops refresh_token + refresh_token_expires_at columns

Design notes:
  - Existing refresh tokens in `users.refresh_token` become invalid after this
    migration. All active sessions must re-authenticate once.
  - AuditEventType enum is created before audit_log and dropped on downgrade
    after the table is dropped.
  - The token_hash column stores a SHA-256 hex digest (64 chars), never the raw JWT.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create AuditEventType ENUM ─────────────────────────────────────────
    auditeventtype = sa.Enum(
        "triage_completed",
        "routing_completed",
        "case_accepted",
        "case_rejected",
        "case_escalated",
        "case_closed",
        "admin_user_created",
        "admin_role_changed",
        "admin_account_activated",
        "admin_tokens_revoked",
        "auth_login",
        "auth_logout",
        "auth_refresh",
        "auth_login_failed",
        "rate_limited",
        name="auditeventtype",
    )
    auditeventtype.create(op.get_bind(), checkfirst=True)

    # ── 2. Create refresh_tokens table ────────────────────────────────────────
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("device_hint", sa.String(255), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    # ── 3. Create audit_log table ─────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.UUID(), primary_key=True, nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "triage_completed",
                "routing_completed",
                "case_accepted",
                "case_rejected",
                "case_escalated",
                "case_closed",
                "admin_user_created",
                "admin_role_changed",
                "admin_account_activated",
                "admin_tokens_revoked",
                "auth_login",
                "auth_logout",
                "auth_refresh",
                "auth_login_failed",
                "rate_limited",
                name="auditeventtype",
                create_type=False,  # already created above
            ),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_role", sa.String(50), nullable=True),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.dialects.postgresql.JSONB() if _is_postgres() else sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_log_event_type", "audit_log", ["event_type"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_resource_type", "audit_log", ["resource_type"])
    op.create_index("ix_audit_log_resource_id", "audit_log", ["resource_id"])
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])
    op.create_index(
        "ix_audit_log_resource_type_id",
        "audit_log",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_log_actor_created",
        "audit_log",
        ["actor_id", "created_at"],
    )

    # ── 4. Drop inline refresh token columns from users ───────────────────────
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("refresh_token")
        batch_op.drop_column("refresh_token_expires_at")


def _is_postgres() -> bool:
    """Detect if running against PostgreSQL (vs SQLite in tests)."""
    try:
        bind = op.get_bind()
        return bind.dialect.name == "postgresql"
    except Exception:
        return False


def downgrade() -> None:
    # ── Restore inline refresh token columns on users ─────────────────────────
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("refresh_token", sa.String(512), nullable=True)
        )

    # ── Drop audit_log ─────────────────────────────────────────────────────────
    op.drop_index("ix_audit_log_actor_created", table_name="audit_log")
    op.drop_index("ix_audit_log_resource_type_id", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_index("ix_audit_log_resource_id", table_name="audit_log")
    op.drop_index("ix_audit_log_resource_type", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_id", table_name="audit_log")
    op.drop_index("ix_audit_log_event_type", table_name="audit_log")
    op.drop_table("audit_log")

    # ── Drop refresh_tokens ────────────────────────────────────────────────────
    op.drop_index("ix_refresh_tokens_token_hash", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    # ── Drop ENUM ─────────────────────────────────────────────────────────────
    sa.Enum(name="auditeventtype").drop(op.get_bind(), checkfirst=True)
