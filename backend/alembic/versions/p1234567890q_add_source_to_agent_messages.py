"""Add source to agent_messages (F2/M2 — R5, "everything into conversation history")

Two things a Mezon-DM conversation needs that a web-only one never did:
distinguish which surface a real user/assistant turn happened on ("web" vs
"mezon"), and mark a row as system-generated (a notification the Attention
Gate delivered, not a reply the AI chose to say) so `_build_history_contents`
can fold it into context without letting it pass as a real turn. Both are
the same column: "web" | "mezon" | "system". NULL on every pre-existing row
means "web" — no backfill needed, since Mezon didn't exist before this.

Revision ID: p1234567890q
Revises: o1234567890p
Create Date: 2026-08-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p1234567890q"
down_revision: Union[str, None] = "o1234567890p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agent_messages", sa.Column("source", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("agent_messages", "source")
