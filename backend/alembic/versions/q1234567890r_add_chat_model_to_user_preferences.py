"""Add chat_model to user_preferences (Mezon bot `*model` command)

Somewhere to record which model a user's chat turns run on, set from a
chat surface that has no settings screen. Nullable, no backfill: NULL
means "no choice recorded" and resolves to the catalogue default, which
is exactly what every existing row wants.

Read only for surface="mezon" — the web keeps its own picker, and having
its "Auto" silently mean a model chosen elsewhere would make that
dropdown lie. See UserPreferences.chat_model's comment.

Revision ID: q1234567890r
Revises: p1234567890q
Create Date: 2026-08-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "q1234567890r"
down_revision: Union[str, None] = "p1234567890q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_preferences", sa.Column("chat_model", sa.String(120), nullable=True))


def downgrade() -> None:
    op.drop_column("user_preferences", "chat_model")
