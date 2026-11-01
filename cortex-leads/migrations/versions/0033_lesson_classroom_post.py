"""A class can post its lesson recaps to a Google Classroom course

Revision ID: 0033
Revises: 0032
"""
import sqlalchemy as sa
from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lesson_source", sa.Column("classroom_course_id", sa.Text()))
    op.add_column("lesson_source", sa.Column("classroom_course_name", sa.Text()))
    op.add_column("lesson_source", sa.Column("classroom_publish", sa.Boolean(), server_default=sa.text("false"), nullable=False))
    op.add_column("lesson", sa.Column("classroom_post_id", sa.Text()))
    op.add_column("lesson", sa.Column("classroom_error", sa.Text()))
    op.add_column("lesson", sa.Column("classroom_attempts", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    for col in ("classroom_attempts", "classroom_error", "classroom_post_id"):
        op.drop_column("lesson", col)
    for col in ("classroom_publish", "classroom_course_name", "classroom_course_id"):
        op.drop_column("lesson_source", col)
