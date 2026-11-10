"""Posting an assignment the way Classroom does: topic, scheduled publish, only some students; and removing one

Revision ID: 0040
Revises: 0039
"""
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE assignment ADD COLUMN IF NOT EXISTS topic_id text")
    op.execute("ALTER TABLE assignment ADD COLUMN IF NOT EXISTS topic_name text")
    op.execute("ALTER TABLE assignment ADD COLUMN IF NOT EXISTS scheduled_at timestamptz")
    op.execute("ALTER TABLE assignment ADD COLUMN IF NOT EXISTS assignees jsonb")
    op.execute("ALTER TABLE assignment DROP CONSTRAINT ck_assignment_state")
    op.execute("ALTER TABLE assignment ADD CONSTRAINT ck_assignment_state CHECK (state in ('draft', 'created', 'rejected', 'failed', 'deleted'))")
    op.execute('ALTER TABLE "class" ADD COLUMN IF NOT EXISTS files_folder_id text')


def downgrade() -> None:
    op.execute("UPDATE assignment SET state = 'rejected' WHERE state = 'deleted'")
    op.execute("ALTER TABLE assignment DROP CONSTRAINT ck_assignment_state")
    op.execute("ALTER TABLE assignment ADD CONSTRAINT ck_assignment_state CHECK (state in ('draft', 'created', 'rejected', 'failed'))")
    op.execute('ALTER TABLE "class" DROP COLUMN IF EXISTS files_folder_id')
    for col in ("assignees", "scheduled_at", "topic_name", "topic_id"):
        op.execute(f"ALTER TABLE assignment DROP COLUMN IF EXISTS {col}")
