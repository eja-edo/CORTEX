"""Add 'user' to attentionitemtype enum (Milestone 4.6 — State Evaluator A1)

`day.review` (A1) isn't about a single task/schedule row — it's a per-user
daily digest, so it needs an item_type that names the user themselves
(`item_id = users.id`) rather than a domain row. See
app/models.py::AttentionItemType's `USER` docstring.

Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction as long
as the new value isn't used in the same transaction — upgrade() only adds
it, so this is safe without the older "run outside a transaction" dance.

Revision ID: l1234567890m
Revises: k1234567890l
Create Date: 2026-08-14
"""

from typing import Sequence, Union

from alembic import op

revision: str = "l1234567890m"
down_revision: Union[str, None] = "k1234567890l"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE attentionitemtype ADD VALUE IF NOT EXISTS 'user'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE. Leaving an unused enum
    # value behind on downgrade matches the existing precedent (the
    # 'goal' value from the dropped Goal entity is still in the enum too)
    # — see AttentionItemType's docstring.
    pass
