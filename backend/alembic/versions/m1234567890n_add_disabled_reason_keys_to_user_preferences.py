"""Add disabled_reason_keys to user_preferences (redesigned 4.5 / A2 follow-up)

A1 wired 6 predicates straight from the backend to the Attention Gate with
no workflow involved (notification_subscribers.py's DIRECT_DELIVERY_
HANDLERS) — there's no WorkflowDefinition row a system-workflow toggle
(the original A2 design) could act on for them. This column is the on/off
switch instead: a per-user list of `reason_key`s to silence, checked by
the Gate before it computes a level at all. See app/models.py::
UserPreferences and docs/planning-v3.md's A2 section.

Revision ID: m1234567890n
Revises: l1234567890m
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "m1234567890n"
down_revision: Union[str, None] = "l1234567890m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_preferences",
        sa.Column(
            "disabled_reason_keys",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_preferences", "disabled_reason_keys")
