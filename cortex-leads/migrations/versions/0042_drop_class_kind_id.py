"""A class no longer points at a class kind: the compose form asks for the kind when a template is picked

Revision ID: 0042
Revises: 0041
"""
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "class" DROP COLUMN IF EXISTS kind_id')


def downgrade() -> None:
    op.execute('ALTER TABLE "class" ADD COLUMN IF NOT EXISTS kind_id uuid REFERENCES class_kind(id) ON DELETE SET NULL')
