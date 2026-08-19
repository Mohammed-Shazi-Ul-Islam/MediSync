"""
alembic/versions/001_add_routing_decision_column.py

Module 03 — Specialist Router: DB migration.

Adds the routing_decision JSONB column to the symptom_reports table.
This column stores the full RoutingDecision output from the HybridSpecialistRouter,
written by the Celery task immediately after Module 02 triage completes.

Column characteristics:
  - Nullable: True  (older rows won't have routing yet)
  - Type: JSONB     (PostgreSQL native JSON binary — supports indexing and querying)
  - Comment documents its purpose for future maintainers

Revision history:
  001 → Initial routing_decision column
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Revision identifiers — used by Alembic
revision = "001_add_routing_decision"
down_revision = None  # First migration — no parent
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "symptom_reports",
        sa.Column(
            "routing_decision",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment=(
                "Module 03: Full RoutingDecision JSON "
                "(specialist, confidence, method, reasoning, alternative_specialists, escalate_to_emergency)"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("symptom_reports", "routing_decision")
