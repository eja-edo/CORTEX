"""A class and a recording can be deleted from the console (the owner's class, a teacher's file)

Revision ID: 0031
Revises: 0030
"""
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON lesson, lesson_source TO cl_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON lesson, lesson_source FROM cl_app")
