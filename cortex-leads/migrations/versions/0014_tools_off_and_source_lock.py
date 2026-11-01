"""WP29 tools and sources: tools a sandbox has switched off, and a soft lock on external sources

Revision ID: 0014
Revises: 0013
"""
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE sandbox ADD COLUMN IF NOT EXISTS tools_off jsonb NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE tool_connector ADD COLUMN IF NOT EXISTS deleted_at timestamptz")
    op.execute("ALTER TABLE tool_connector ADD COLUMN IF NOT EXISTS deleted_by text")
    op.execute("ALTER TABLE tool_connector ADD COLUMN IF NOT EXISTS alert text")


def downgrade() -> None:
    op.execute("ALTER TABLE tool_connector DROP COLUMN IF EXISTS alert, DROP COLUMN IF EXISTS deleted_by, DROP COLUMN IF EXISTS deleted_at")
    op.execute("ALTER TABLE sandbox DROP COLUMN IF EXISTS tools_off")
