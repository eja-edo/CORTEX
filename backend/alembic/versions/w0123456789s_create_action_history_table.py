"""Create action_history table (fixes a gap present since Milestone 1.5/1.6)

`app/ai/agents/action_snapshot_store.py` has always tried to write a Postgres
audit row alongside every Redis snapshot — that INSERT has been silently
failing since the module was written, because this table never existed. The
`except Exception: logger.warning(...)` around it swallowed every failure, so
`revert_action` kept working (Redis carries the 24h hot path) while the
90-day-ish audit trail quietly never accumulated anything.

Found by actually exercising the chat endpoint end to end: the failed INSERT
used to also roll back the *caller's* request session (fixed separately, see
action_snapshot_store.py's docstring), which is what surfaced this as a
crash instead of a silent gap.

`action_id` is a plain string, not a UUID column: the application always
treats it as an opaque identifier (a Redis key, `Command.command_id`) and
never casts it, so this table doesn't add a constraint the app layer itself
doesn't enforce. It carries the UNIQUE constraint the existing
`ON CONFLICT DO NOTHING` INSERT depends on.

`id` needs a **server-side** default (`gen_random_uuid()`), not just the
model's Python-side `default=uuid.uuid4`. `action_snapshot_store.py` writes
this table with a raw `text()` INSERT rather than the ORM, and a Python-side
`Column(default=...)` only fires through `session.add()` — a raw SQL INSERT
never sees it. Missing this the first time around meant the very first write
against this table failed on a NOT NULL violation on `id`, caught by the
same broad `except Exception` that had hidden the table's total absence.

Revision ID: w0123456789s
Revises: v0123456789r
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "w0123456789s"
down_revision: Union[str, None] = "v0123456789r"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "action_history",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column(
            "action_type", sa.String(50), nullable=False, server_default=sa.text("'snapshot'")
        ),
        sa.Column("action_id", sa.String(64), nullable=False),
        sa.Column("before_state", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column(
            "is_reverted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("reverted_at", sa.DateTime(), nullable=True),
    )

    op.create_index("ix_action_history_user_id", "action_history", ["user_id"])
    # Required by the existing `ON CONFLICT DO NOTHING` INSERT — without a
    # unique constraint on action_id, that clause has no conflict to resolve
    # against and duplicate snapshot writes would raise instead of no-op.
    op.create_index(
        "ix_action_history_action_id", "action_history", ["action_id"], unique=True
    )
    op.create_index("ix_action_history_user_created", "action_history", ["user_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_action_history_user_created", table_name="action_history")
    op.drop_index("ix_action_history_action_id", table_name="action_history")
    op.drop_index("ix_action_history_user_id", table_name="action_history")
    op.drop_table("action_history")
