"""WP29 skills editable in place: the form as the person filled it, and a soft delete (hidden, restorable)

Revision ID: 0013
Revises: 0012
"""
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE skill_version ADD COLUMN IF NOT EXISTS form_spec jsonb")
    op.execute("ALTER TABLE skill_version ADD COLUMN IF NOT EXISTS deleted_at timestamptz")
    op.execute("ALTER TABLE skill_version ADD COLUMN IF NOT EXISTS deleted_by text")
    op.execute("ALTER TABLE skill_version ADD COLUMN IF NOT EXISTS edited_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE skill_version DROP COLUMN IF EXISTS edited_at, DROP COLUMN IF EXISTS deleted_by, DROP COLUMN IF EXISTS deleted_at, DROP COLUMN IF EXISTS form_spec")
