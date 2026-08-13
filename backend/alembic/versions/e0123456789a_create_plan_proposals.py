"""Create plan_proposals table (3.2 AI Planner — reviewable Task/Event proposals)

A `PlanProposal` holds a structured list of draft task/event items an AI
skill (`planning`) proposes after clarifying a vague user want in
conversation. Nothing is created in `tasks`/`schedules` until the user
approves via `POST /plan-proposals/{id}/approve`, which replays each item
through the existing `task.create`/`schedule.create` commands.

Deliberately simpler than `note_edit_proposals`: items describe rows to be
created, not a patch against existing content, so there's no
base_revision/base_version optimistic-lock column and no "applying"
intermediate status.

Revision ID: e0123456789a
Revises: d0123456789z
Create Date: 2026-08-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e0123456789a"
down_revision: Union[str, None] = "d0123456789z"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "plan_proposals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("creator_type", sa.String(length=20), nullable=False),
        sa.Column("creator_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plan_proposals_user_id"), "plan_proposals", ["user_id"], unique=False)
    op.create_index("ix_plan_proposals_user_status", "plan_proposals", ["user_id", "status"], unique=False)
    op.create_index("ix_plan_proposals_expires", "plan_proposals", ["status", "expires_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_plan_proposals_expires", table_name="plan_proposals")
    op.drop_index("ix_plan_proposals_user_status", table_name="plan_proposals")
    op.drop_index(op.f("ix_plan_proposals_user_id"), table_name="plan_proposals")
    op.drop_table("plan_proposals")
