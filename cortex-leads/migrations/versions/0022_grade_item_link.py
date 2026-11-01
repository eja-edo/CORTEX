"""WP34: grade_item.link, where the teacher opens the submission in Classroom

Revision ID: 0022
Revises: 0021
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grade_item ADD COLUMN link text")


def downgrade() -> None:
    op.execute("ALTER TABLE grade_item DROP COLUMN link")
