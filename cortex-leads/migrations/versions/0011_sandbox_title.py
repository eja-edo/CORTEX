"""WP27 sandbox.title: the owner's name for a sandbox (`name` stays the internal key)

Revision ID: 0011
Revises: 0010
"""
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sandbox ADD COLUMN IF NOT EXISTS title text")


def downgrade() -> None:
    op.execute("ALTER TABLE sandbox DROP COLUMN IF EXISTS title")
