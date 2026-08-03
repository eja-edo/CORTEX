"""add summary cursor fields (last_summary_message_id, tokens_since_last_summary, messages_since_last_summary)

Revision ID: q0123456789m
Revises: p0123456789l
Create Date: 2026-07-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "q0123456789m"
down_revision: Union[str, None] = "p0123456789l"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("last_summary_message_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_agent_conversations_last_summary_msg",
        "agent_conversations",
        ["last_summary_message_id"],
    )
    op.create_foreign_key(
        "fk_agent_conversations_last_summary_msg",
        "agent_conversations",
        "agent_messages",
        ["last_summary_message_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column(
        "agent_conversations",
        sa.Column(
            "tokens_since_last_summary",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "agent_conversations",
        sa.Column(
            "messages_since_last_summary",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_agent_conversations_last_summary_msg",
        "agent_conversations",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_agent_conversations_last_summary_msg",
        table_name="agent_conversations",
    )
    op.drop_column("agent_conversations", "messages_since_last_summary")
    op.drop_column("agent_conversations", "tokens_since_last_summary")
    op.drop_column("agent_conversations", "last_summary_message_id")
