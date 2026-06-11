"""Add context JSONB column to agent_messages.

Stores structured context (pills, runtime info) separately from the
actual user message content, so the frontend can display only the
user's original text while the LLM still receives the full context.

Revision ID: i4567890123e
Revises: h3456789012d_add_agent_memory_fields
Create Date: 2026-06-11
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "i4567890123e"
down_revision: Union[str, None] = "h3456789012d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_messages",
        sa.Column("context", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_messages", "context")
