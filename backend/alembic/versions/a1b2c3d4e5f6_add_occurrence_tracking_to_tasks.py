"""Add per-occurrence completion tracking to tasks

A checklist task linked to a *recurring* event (`related_event_id` pointing
at a Schedule with a recurrence rule) used to have exactly one `status` for
every occurrence, because every occurrence shares the root Schedule's id
(see `RecurrenceService.generate_instances`) and the task is one row.
Ticking it complete for one occurrence showed as complete everywhere.

Mirrors `schedules`' own exception mechanism (see
`b9536f24e86d_add_recurrence_reminders_and_sync_queue.py`) exactly: the task
most callers see is the template (these three columns null); an
"exception" row — a normal `tasks` row with its own status/title/description
— is created lazily on first write to one occurrence, with `recurrence_id`
pointing back at the template and `original_start_time` identifying which
occurrence it overrides.

Revision ID: a1b2c3d4e5f6
Revises: q1234567890r
Create Date: 2026-08-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "q1234567890r"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("recurrence_id", sa.UUID(), nullable=True))
    op.add_column(
        "tasks", sa.Column("original_start_time", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("is_exception", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )

    op.create_foreign_key(
        "fk_tasks_recurrence_id", "tasks", "tasks", ["recurrence_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(
        "ix_tasks_recurrence_id",
        "tasks",
        ["recurrence_id"],
        postgresql_where=sa.text("recurrence_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_recurrence_id", table_name="tasks")
    op.drop_constraint("fk_tasks_recurrence_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "is_exception")
    op.drop_column("tasks", "original_start_time")
    op.drop_column("tasks", "recurrence_id")
