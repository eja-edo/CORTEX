"""Assignments carry attachments: Drive files and links go to Classroom with the course work

Revision ID: 0032
Revises: 0031
"""
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assignment_draft ADD COLUMN materials jsonb NOT NULL DEFAULT '[]'::jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE assignment_draft DROP COLUMN materials")
