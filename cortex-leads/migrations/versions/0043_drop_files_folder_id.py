"""Cortex no longer puts files in a teacher's Drive for assignments (attachments are picked in Google's own dialog), so the folder it remembered is gone

Revision ID: 0043
Revises: 0042
"""
from alembic import op

revision = "0043"
down_revision = "0042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('ALTER TABLE "class" DROP COLUMN IF EXISTS files_folder_id')


def downgrade() -> None:
    op.execute('ALTER TABLE "class" ADD COLUMN IF NOT EXISTS files_folder_id text')
