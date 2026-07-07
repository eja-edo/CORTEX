"""Add CRON_EVENT to scheduletype enum

Revision ID: k6789012345g
Revises: j5678901234f
Create Date: 2026-06-29
"""

from typing import Sequence, Union

from alembic import op


revision: str = "k6789012345g"
down_revision: Union[str, None] = "j5678901234f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE scheduletype ADD VALUE 'CRON_EVENT'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values. This is a no-op.
    pass
