"""WP38: a class is a watched folder with its own team webhook; uploads go by class, Drive targets are retired

Revision ID: 0030
Revises: 0029
"""
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE lesson_source ADD COLUMN owned boolean NOT NULL DEFAULT false")  # the folder was made by Cortex, so Cortex may write to it
    op.execute("ALTER TABLE lesson_source ADD COLUMN notify_target_id uuid REFERENCES notify_target(id)")
    op.execute("UPDATE drive_target SET active = false")  # a class holds its own folder now; the rows stay for the lessons that point at them


def downgrade() -> None:
    op.execute("ALTER TABLE lesson_source DROP COLUMN notify_target_id")
    op.execute("ALTER TABLE lesson_source DROP COLUMN owned")
