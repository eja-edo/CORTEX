"""WP37: a Drive target may use a folder the teacher already had (the watched one) instead of one Cortex makes

Revision ID: 0026
Revises: 0025
"""
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE drive_target ADD COLUMN folder_adopted boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE drive_target DROP COLUMN folder_adopted")
