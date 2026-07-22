"""Add tool_call_id and turn_id columns to agent_messages

Revision ID: o0123456789k
Revises: n9012345678j
Create Date: 2026-07-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "o0123456789k"
down_revision: Union[str, None] = "n9012345678j"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_messages",
        sa.Column("tool_call_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "agent_messages",
        sa.Column("turn_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_agent_messages_turn_id",
        "agent_messages",
        ["turn_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_messages_turn_id", table_name="agent_messages")
    op.drop_column("agent_messages", "turn_id")
    op.drop_column("agent_messages", "tool_call_id")
