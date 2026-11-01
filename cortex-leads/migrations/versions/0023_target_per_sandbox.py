"""WP35: notify_target.sandbox_id (a channel per sandbox) and grade_item.course_name (the class a submission is in)

Revision ID: 0023
Revises: 0022
"""
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE notify_target ADD COLUMN sandbox_id uuid REFERENCES sandbox(id)")
    op.execute("ALTER TABLE grade_item ADD COLUMN course_name text")


def downgrade() -> None:
    op.execute("ALTER TABLE grade_item DROP COLUMN course_name")
    op.execute("ALTER TABLE notify_target DROP COLUMN sandbox_id")
