"""Create attention_bundle_queue table (Milestone 6.1 M3 — bundling)

M2 (i1234567890j / attention_gate.py) can silence a non-critical candidate
while the user is busy, but had nowhere to put it — a busy-silenced
candidate was just gone, not "held and merged after the meeting" the way
the planning doc's own acceptance scenario requires (8 candidates during a
meeting -> 0 during, 1 bundled notification after). This table is that
holding place: a row per busy-silenced candidate, `flushed_at` null until
`AttentionBundleWorker` (new, mirrors StateEvaluator's poll shape) finds
the user free again and turns every unflushed row for them into one
Notification.

Denormalized on purpose (`title`/`body`/`payload`/`actions` copied in, not
looked up again at flush time): the item that triggered a candidate can
change or be deleted between "silenced during the meeting" and "flushed
after it", and the bundle should say what was true when it was silenced,
not re-derive a possibly-different current state.

`attention_log_id` links back to the specific SILENT decision this row
follows from (6.9 provenance); `bundle_notification_id` is null until
flushed, then names the one Notification this row was folded into.

Revision ID: j1234567890k
Revises: i1234567890j
Create Date: 2026-08-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "j1234567890k"
down_revision: Union[str, None] = "i1234567890j"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attention_bundle_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "item_type",
            postgresql.ENUM(
                "task", "goal", "commitment", "schedule",
                name="attentionitemtype", create_type=False,
            ),
            nullable=False,
        ),
        # No FK — same reasoning as attention_log.item_id.
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_key", sa.String(100), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("actions", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "attention_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("attention_log.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("queued_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("flushed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "bundle_notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # The sweep's own query shape: "unflushed rows, grouped by user".
    op.create_index(
        "ix_attention_bundle_queue_user_flushed",
        "attention_bundle_queue",
        ["user_id", "flushed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_attention_bundle_queue_user_flushed", table_name="attention_bundle_queue")
    op.drop_table("attention_bundle_queue")
