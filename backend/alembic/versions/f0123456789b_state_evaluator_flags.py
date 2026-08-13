"""Create state_evaluator_flags table (Milestone 4.6 — State Evaluator)

The evaluator's own idempotency bookkeeping: a row means "this item
currently has this condition" (e.g. task X is overdue). Deleted the moment
the condition stops holding, so a later re-transition publishes again
instead of being suppressed forever. See app/models.py::StateEvaluatorFlag
and app/services/state_evaluator.py for the full reasoning.

Reuses the `attentionitemtype` enum created by the attention_log migration
(u0123456789q) rather than declaring a new one — same polymorphic
item_type/item_id shape, different question (detection vs. delivery).

Revision ID: f0123456789b
Revises: e0123456789a
Create Date: 2026-08-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "f0123456789b"
down_revision: Union[str, None] = "e0123456789a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "state_evaluator_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "item_type",
            postgresql.ENUM(
                "task", "goal", "commitment", "schedule",
                name="attentionitemtype", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("flag_key", sa.String(100), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("item_type", "item_id", "flag_key", name="uq_state_evaluator_flag"),
    )
    op.create_index("ix_state_evaluator_flags_user_id", "state_evaluator_flags", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_state_evaluator_flags_user_id", table_name="state_evaluator_flags")
    op.drop_table("state_evaluator_flags")
