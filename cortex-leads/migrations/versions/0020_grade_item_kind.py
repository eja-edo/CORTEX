"""WP34: grade_item.content_kind says whether the work was read from text, a PDF, a Word file, audio or video

Revision ID: 0020
Revises: 0019
"""
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE grade_item ADD COLUMN content_kind text")


def downgrade() -> None:
    op.execute("ALTER TABLE grade_item DROP COLUMN content_kind")
