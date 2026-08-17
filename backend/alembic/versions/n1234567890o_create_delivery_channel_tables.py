"""Create user_channels + notification_deliveries (delivery layer, bước 0)

Splits "create a Notification" from "deliver it somewhere". Until now
`create_notification_async` did both, with SSE hardcoded as the only
route — so a nudge computed while the user had no browser tab open never
reached them. These two tables are the registry of other routes and the
outbox that drives them; see app/services/delivery/ and the model
docstrings in app/models.py.

Also extends the existing `attentionchannel` enum with the channels the
roadmap already names (slack, mezon, webhook), so bước 1-2 add an adapter
file and nothing else. Values are added here rather than one-per-feature
because ALTER TYPE ... ADD VALUE cannot run inside a transaction block
alongside the rest of a migration, and doing it three separate times would
be three migrations paying that cost for nothing.

Revision ID: n1234567890o
Revises: m1234567890n
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "n1234567890o"
down_revision: Union[str, None] = "m1234567890n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_CHANNELS = ("slack", "mezon", "webhook")


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE needs its own transaction on PostgreSQL < 12
    # and is safest committed before any table below references the type.
    # IF NOT EXISTS keeps this re-runnable against a partially migrated DB.
    with op.get_context().autocommit_block():
        for value in _NEW_CHANNELS:
            op.execute(f"ALTER TYPE attentionchannel ADD VALUE IF NOT EXISTS '{value}'")

    delivery_status = postgresql.ENUM(
        "pending", "sending", "sent", "failed", "skipped",
        name="deliverystatus",
        create_type=False,
    )
    delivery_status.create(op.get_bind(), checkfirst=True)

    # Both enums already exist in the database (attentionchannel from the
    # attention_log migration, attentionlevel from the same). Declaring
    # them with create_type=False stops Alembic from trying to CREATE TYPE
    # a second time when it builds these tables.
    attention_channel = postgresql.ENUM(name="attentionchannel", create_type=False)
    attention_level = postgresql.ENUM(name="attentionlevel", create_type=False)

    op.create_table(
        "user_channels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("channel", attention_channel, nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("config", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("min_level", attention_level, nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "channel", "address", name="uq_user_channels_user_channel_address"),
    )
    op.create_index("ix_user_channels_user_id", "user_channels", ["user_id"])
    op.create_index("ix_user_channels_user_enabled", "user_channels", ["user_id", "enabled"])

    op.create_table(
        "notification_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "notification_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("channel", attention_channel, nullable=False),
        sa.Column(
            "user_channel_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_channels.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("status", delivery_status, nullable=False, server_default="pending"),
        sa.Column("skip_reason", sa.String(64), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint(
            "notification_id", "user_channel_id", name="uq_notification_deliveries_notif_channel"
        ),
    )
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
    op.create_index("ix_notification_deliveries_user_id", "notification_deliveries", ["user_id"])
    op.create_index("ix_notification_deliveries_next_attempt_at", "notification_deliveries", ["next_attempt_at"])
    op.create_index(
        "ix_notification_deliveries_claimable", "notification_deliveries", ["status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("user_channels")
    op.execute("DROP TYPE IF EXISTS deliverystatus")
    # The three added `attentionchannel` values are intentionally left in
    # place: PostgreSQL has no ALTER TYPE ... DROP VALUE, and rebuilding the
    # enum would require rewriting attention_log, which holds history.
