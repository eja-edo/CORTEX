"""A Google account can be deleted from the console once nothing uses it

Revision ID: 0035
Revises: 0034
"""
from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("GRANT DELETE ON google_account TO cl_app")


def downgrade() -> None:
    op.execute("REVOKE DELETE ON google_account FROM cl_app")
