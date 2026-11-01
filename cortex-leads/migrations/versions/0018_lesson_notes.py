"""WP32: lesson.notes keeps what each piece of a long transcript yielded, so a retry resumes instead of rereading

Revision ID: 0018
Revises: 0017
"""
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lesson ADD COLUMN notes jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE lesson DROP COLUMN notes")
