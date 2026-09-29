"""Add agent execution_mode (auto/manual) and pending tool calls

Adds a per-conversation `execution_mode` switch. `auto` keeps today's
behavior (the agent runs every tool call it decides on). `manual` makes the
turn loop stop before executing any tool call and persist it to
`agent_pending_tool_calls` instead — the SSE stream ends with an
`awaiting_approval` event, and a separate `POST
/agent/conversations/{id}/tool-calls/resolve` call executes (or synthesizes
a rejection for) each pending call and resumes the turn loop.

No `status` column on `agent_pending_tool_calls`: a row's existence *is*
"pending" — resolving a decision deletes the row, same lifecycle as a lock
row rather than a state machine like `plan_proposals`.

Revision ID: t9012345678u
Revises: s2345678901t
Create Date: 2026-09-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "t9012345678u"
down_revision: Union[str, None] = "s2345678901t"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("execution_mode", sa.String(length=10), nullable=False, server_default=sa.text("'auto'")),
    )

    op.create_table(
        "agent_pending_tool_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column("turn_id", sa.UUID(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["agent_conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_pending_tool_calls_conversation_id",
        "agent_pending_tool_calls", ["conversation_id"], unique=False,
    )
    op.create_index(
        "ix_agent_pending_tool_calls_turn_id",
        "agent_pending_tool_calls", ["turn_id"], unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_pending_tool_calls_turn_id", table_name="agent_pending_tool_calls")
    op.drop_index("ix_agent_pending_tool_calls_conversation_id", table_name="agent_pending_tool_calls")
    op.drop_table("agent_pending_tool_calls")
    op.drop_column("agent_conversations", "execution_mode")
