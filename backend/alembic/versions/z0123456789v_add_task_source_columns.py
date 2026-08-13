"""Add source_conversation_id/source_message_id to tasks

Provenance for a task extracted from a conversation — the same two columns
`Commitment` had, moved here as part of folding Commitment into Task. Null
for every other creation path, so "where did Cortex get this?" stays
answerable without becoming mandatory.

The content-fingerprint index (`ix_tasks_user_status_content`) is the
`Commitment` extraction pipeline's "did the user already reject this?"
lookup, moved to key on `title` alone now that there's no separate
`counterparty`/`expected_action` pair — must stay identical to
`app.repositories.tasks.normalized()`'s expression or the lookup silently
stops using the index and starts scanning.

Revision ID: z0123456789v
Revises: y0123456789u
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "z0123456789v"
down_revision: Union[str, None] = "y0123456789u"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "source_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_source_conversation_id", "tasks", ["source_conversation_id"])
    op.execute(
        "CREATE INDEX ix_tasks_user_status_content ON tasks "
        "(user_id, status, lower(btrim(title)))"
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_user_status_content", table_name="tasks")
    op.drop_index("ix_tasks_source_conversation_id", table_name="tasks")
    op.drop_constraint("tasks_source_message_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "source_message_id")
    op.drop_constraint("tasks_source_conversation_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "source_conversation_id")
