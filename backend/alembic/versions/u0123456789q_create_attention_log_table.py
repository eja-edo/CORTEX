"""Create attention_log table (Milestone 2.9 — Attention Log)

Lands in Phase 2 rather than Phase 6 on purpose: this state hangs off the
items themselves (task/goal/commitment), so building the three entities
without it means migrating all three later. One small migration now instead
of a large one after.

`item_id` carries no foreign key. It points at `tasks`, `goals`,
`commitments` (2.4) or `schedules` depending on `item_type` — polymorphic,
so no single FK is possible. It's also meant to outlive its target: "Cortex
already nagged about this" stays true after the item is deleted, and a
CASCADE would erase exactly the history 6.9 is supposed to learn from.

The index column order is the dedup lookup's order:
(user_id, item_id, reason_key, surfaced_at).

Revision ID: u0123456789q
Revises: t0123456789p
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "u0123456789q"
down_revision: Union[str, None] = "t0123456789p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

item_type_enum = postgresql.ENUM(
    "task", "goal", "commitment", "schedule", name="attentionitemtype"
)
level_enum = postgresql.ENUM(
    "silent", "inform", "recommend", "ask", "act", name="attentionlevel"
)
# telegram/email have no delivery path before Phase 5. Declared now so
# turning one on is a code change, not an ALTER TYPE on a table that by then
# holds live history.
channel_enum = postgresql.ENUM(
    "in_app", "push", "telegram", "email", name="attentionchannel"
)
response_enum = postgresql.ENUM(
    "accepted", "dismissed", "ignored", "no_response", name="attentionresponse"
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in (item_type_enum, level_enum, channel_enum, response_enum):
        enum.create(bind, checkfirst=True)

    op.create_table(
        "attention_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "item_type",
            postgresql.ENUM(
                "task", "goal", "commitment", "schedule",
                name="attentionitemtype", create_type=False,
            ),
            nullable=False,
        ),
        # No FK — see the module docstring.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_key", sa.String(100), nullable=False),
        sa.Column("surfaced_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column(
            "level",
            postgresql.ENUM(
                "silent", "inform", "recommend", "ask", "act",
                name="attentionlevel", create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "channel",
            postgresql.ENUM(
                "in_app", "push", "telegram", "email",
                name="attentionchannel", create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'in_app'"),
        ),
        sa.Column(
            "response",
            postgresql.ENUM(
                "accepted", "dismissed", "ignored", "no_response",
                name="attentionresponse", create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'no_response'"),
        ),
        sa.Column("responded_at", sa.DateTime(), nullable=True),
    )

    op.create_index("ix_attention_log_user_id", "attention_log", ["user_id"])
    op.create_index("ix_attention_log_surfaced_at", "attention_log", ["surfaced_at"])
    # M1's index, in dedup lookup order.
    op.create_index(
        "ix_attention_log_user_item_reason_surfaced",
        "attention_log",
        ["user_id", "item_id", "reason_key", "surfaced_at"],
    )
    # 6.9's read direction: outcomes per reason.
    op.create_index(
        "ix_attention_log_user_reason_response",
        "attention_log",
        ["user_id", "reason_key", "response"],
    )


def downgrade() -> None:
    op.drop_index("ix_attention_log_user_reason_response", table_name="attention_log")
    op.drop_index("ix_attention_log_user_item_reason_surfaced", table_name="attention_log")
    op.drop_index("ix_attention_log_surfaced_at", table_name="attention_log")
    op.drop_index("ix_attention_log_user_id", table_name="attention_log")
    op.drop_table("attention_log")

    bind = op.get_bind()
    for enum in (response_enum, channel_enum, level_enum, item_type_enum):
        enum.drop(bind, checkfirst=True)
