"""Add reason_key/attention_level/attention_log_id to notifications (6.1 M2)

The planning doc flagged this gap explicitly: "Notification không có
importance / bundling key / trạng thái phản hồi". Milestone 6.1 M2 makes
the Attention Gate compute a real `AttentionLevel` and write an
`attention_log` row for every candidate — this migration lets the
resulting Notification carry that same reason_key/level back, and link to
the exact attention_log row that decided to create it. Without this a
notification and the reasoning that produced it can't be joined, which
blocks two things already on the roadmap: the "đừng nhắc kiểu này nữa"
downgrade button (4.5 M3) needs `reason_key` to know what to mute, and 6.9's
feedback loop needs the link to `attention_log` to read the response back.

All three columns are nullable: existing rows (and any caller that still
goes through the pass-through branch — see attention_gate.py) have none of
this, and that's a valid, permanent state, not a to-be-backfilled one.

`attention_level` reuses the `attentionlevel` enum type created in
u0123456789q (create_type=False) rather than defining a second one.

Revision ID: i1234567890j
Revises: h1234567890i
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "i1234567890j"
down_revision: Union[str, None] = "h1234567890i"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("reason_key", sa.String(100), nullable=True))
    op.add_column(
        "notifications",
        sa.Column(
            "attention_level",
            postgresql.ENUM(
                "silent", "inform", "recommend", "ask", "act",
                name="attentionlevel", create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "notifications",
        sa.Column("attention_log_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notifications_attention_log_id",
        "notifications",
        "attention_log",
        ["attention_log_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notifications_attention_log_id", "notifications", ["attention_log_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_attention_log_id", table_name="notifications")
    op.drop_constraint(
        "fk_notifications_attention_log_id", "notifications", type_="foreignkey"
    )
    op.drop_column("notifications", "attention_log_id")
    op.drop_column("notifications", "attention_level")
    op.drop_column("notifications", "reason_key")
