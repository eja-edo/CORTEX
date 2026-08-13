"""Add needs_reauth to calendar_connections

Set when Google rejects a refresh_token as invalid_grant (revoked or
expired) — a permanent failure that a retry can never fix. Lets
ensure_access_token() fail fast instead of hitting Google's OAuth
endpoint again on every subsequent sync, and lets the API/frontend show
a "reconnect" state instead of a generic sync error.

Revision ID: h1234567890i
Revises: g0123456789c
Create Date: 2026-08-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1234567890i"
down_revision: Union[str, None] = "g0123456789c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "calendar_connections",
        sa.Column("needs_reauth", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("calendar_connections", "needs_reauth")
