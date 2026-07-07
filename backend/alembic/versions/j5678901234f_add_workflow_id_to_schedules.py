"""Add workflow_id column to schedules table

Revision ID: j5678901234f
Revises: i4567890123e
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "j5678901234f"
down_revision: Union[str, None] = "i4567890123e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "schedules",
        sa.Column("workflow_id", UUID(as_uuid=True), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column("schedules", "workflow_id")
