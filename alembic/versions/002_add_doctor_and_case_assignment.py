"""
alembic/versions/002_add_doctor_and_case_assignment.py

Module 04 + 05 — Notification Pipeline & Doctor Dashboard: DB migration.

Creates:
  - doctors table (doctor profiles — 1:1 with users)
  - case_assignments table (offer/accept/reject/expired escalation chain)

Modifies:
  - symptom_reports: adds assigned_doctor_id (nullable FK → doctors.id)

Design notes:
  - assignmentstatus ENUM is created before the table that uses it, and dropped
    in downgrade() only after the table is dropped.
  - assigned_doctor_id uses ON DELETE SET NULL so deleting a doctor row doesn't
    cascade-delete patient reports.
  - case_assignments.celery_escalation_task_id is VARCHAR(255) — stores the
    Celery task UUID so we can revoke the countdown if a doctor responds early.

Revision history:
  001 → routing_decision column (Module 03)
  002 → doctors + case_assignments + assigned_doctor_id (Module 04+05)
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers — used by Alembic
revision = "002_add_doctor_and_case_assignment"
down_revision = "001_add_routing_decision"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Create assignmentstatus ENUM type ───────────────────────────────────
    assignment_status_enum = postgresql.ENUM(
        "offered", "accepted", "rejected", "expired",
        name="assignmentstatus",
        create_type=True,
    )
    assignment_status_enum.create(op.get_bind(), checkfirst=True)

    # ── 2. Create doctors table ────────────────────────────────────────────────
    op.create_table(
        "doctors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
        ),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "specialty",
            sa.String(100),
            nullable=False,
            comment="SpecialistType code, e.g. 'cardiologist'. Indexed for routing lookups.",
        ),
        sa.Column("license_number", sa.String(100), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(20), unique=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column(
            "is_available",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
            comment="False = doctor is off-queue; routing skips them.",
        ),
        sa.Column(
            "max_concurrent_cases",
            sa.Integer,
            nullable=False,
            server_default="5",
            comment="Max simultaneous offered+accepted cases before routing skips this doctor.",
        ),
        sa.Column("bio", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_doctors_user_id",   "doctors", ["user_id"])
    op.create_index("ix_doctors_specialty", "doctors", ["specialty"])
    op.create_index("ix_doctors_phone",     "doctors", ["phone"])

    # ── 3. Create case_assignments table ───────────────────────────────────────
    op.create_table(
        "case_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("symptom_reports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "offered", "accepted", "rejected", "expired",
                name="assignmentstatus",
                create_type=False,  # already created above
            ),
            nullable=False,
            server_default="offered",
        ),
        sa.Column(
            "offered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("celery_escalation_task_id", sa.String(255), nullable=True),
        sa.Column("doctor_notes", sa.Text, nullable=True),
    )
    op.create_index("ix_case_assignments_report_id", "case_assignments", ["report_id"])
    op.create_index("ix_case_assignments_doctor_id", "case_assignments", ["doctor_id"])
    op.create_index("ix_case_assignments_status",    "case_assignments", ["status"])

    # ── 4. Add assigned_doctor_id to symptom_reports ──────────────────────────
    op.add_column(
        "symptom_reports",
        sa.Column(
            "assigned_doctor_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("doctors.id", ondelete="SET NULL"),
            nullable=True,
            comment="Module 04: Denormalised FK to the currently active doctor assignment.",
        ),
    )
    op.create_index(
        "ix_symptom_reports_assigned_doctor_id",
        "symptom_reports",
        ["assigned_doctor_id"],
    )


def downgrade() -> None:
    # Reverse in dependency order
    op.drop_index("ix_symptom_reports_assigned_doctor_id", table_name="symptom_reports")
    op.drop_column("symptom_reports", "assigned_doctor_id")

    op.drop_index("ix_case_assignments_status",    table_name="case_assignments")
    op.drop_index("ix_case_assignments_doctor_id", table_name="case_assignments")
    op.drop_index("ix_case_assignments_report_id", table_name="case_assignments")
    op.drop_table("case_assignments")

    op.drop_index("ix_doctors_phone",     table_name="doctors")
    op.drop_index("ix_doctors_specialty", table_name="doctors")
    op.drop_index("ix_doctors_user_id",   table_name="doctors")
    op.drop_table("doctors")

    # Drop the ENUM type last
    sa.Enum(name="assignmentstatus").drop(op.get_bind(), checkfirst=True)
