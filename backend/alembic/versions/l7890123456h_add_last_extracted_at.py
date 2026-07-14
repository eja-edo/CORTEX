"""Add last_extracted_at to agent_conversations

Revision ID: l7890123456h
Revises: k6789012345g
Create Date: 2026-07-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l7890123456h"
down_revision: Union[str, None] = "dcfccc969303"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_conversations",
        sa.Column("last_extracted_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_conversations", "last_extracted_at")
