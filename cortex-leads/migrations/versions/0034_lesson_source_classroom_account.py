"""The Google account that posts a class's recaps to Classroom may differ from the one that owns its Drive folder

Revision ID: 0034
Revises: 0033
"""
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lesson_source", sa.Column("classroom_account_id", sa.Uuid(), sa.ForeignKey("google_account.id")))


def downgrade() -> None:
    op.drop_column("lesson_source", "classroom_account_id")
