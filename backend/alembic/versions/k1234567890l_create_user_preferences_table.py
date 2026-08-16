"""Create user_preferences table (Milestone 6.2 — quiet hours)

The planning doc calls this the cheapest, highest-impact half of
interruptibility: `schedules` already answers "is the user busy right now"
(4.6/6.1's `is_user_busy`); this answers "is it just a bad time of day
regardless of the calendar" — no new signal needed, two nullable columns.

No row is seeded for existing users. A missing row means "no quiet hours
configured" (the Gate's quiet-hours check is a no-op), not an error or a
migration gap — see UserPreferences' docstring in app/models.py.

Revision ID: k1234567890l
Revises: j1234567890k
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "k1234567890l"
down_revision: Union[str, None] = "j1234567890k"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_preferences",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True
        ),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )


def downgrade() -> None:
    op.drop_table("user_preferences")
