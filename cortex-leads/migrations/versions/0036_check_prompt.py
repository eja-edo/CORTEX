"""A grading guide carries the teacher's own words on how to check the work

Revision ID: 0036
Revises: 0035
"""
import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignment_draft", sa.Column("check_prompt", sa.Text()))
    op.add_column("grading_guide", sa.Column("check_prompt", sa.Text()))


def downgrade() -> None:
    op.drop_column("grading_guide", "check_prompt")
    op.drop_column("assignment_draft", "check_prompt")
