"""Create channel_link_codes (M1 — proving a chat account belongs to a user)

A Mezon user id is a number the bot receives; receiving it proves nothing
about who owns the Cortex account. This table holds the one-time code that
does prove it — minted in the web app where the person is already
authenticated, typed into the chat. Same lifecycle as `oauth_states`.

Revision ID: o1234567890p
Revises: n1234567890o
Create Date: 2026-08-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o1234567890p"
down_revision: Union[str, None] = "n1234567890o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    attention_channel = postgresql.ENUM(name="attentionchannel", create_type=False)

    op.create_table(
        "channel_link_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("channel", attention_channel, nullable=False),
        sa.Column("code", sa.String(12), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("redeemed_address", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_channel_link_codes_user_id", "channel_link_codes", ["user_id"])
    op.create_index("ix_channel_link_codes_code", "channel_link_codes", ["code"])
    # Redemption looks up by (code, channel) — a code is only meaningful for
    # the channel it was minted for, so the lookup must not match across
    # channels even if two codes collide.
    op.create_index("ix_channel_link_codes_code_channel", "channel_link_codes", ["code", "channel"])


def downgrade() -> None:
    op.drop_table("channel_link_codes")
