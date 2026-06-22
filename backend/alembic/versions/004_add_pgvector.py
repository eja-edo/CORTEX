"""add pgvector extension

Revision ID: 004
Revises: i4567890123e
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op


revision: str = '004'
down_revision: Union[str, None] = 'i4567890123e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')


def downgrade() -> None:
    op.execute('DROP EXTENSION IF EXISTS pg_trgm')
    op.execute('DROP EXTENSION IF EXISTS vector')
