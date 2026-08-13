"""Add tasks.parent_task_id (sub-tasks)

Self-referential FK so a task can carry a checklist of its own — the same
role `related_event_id` already plays for "tasks that belong to an event",
now available for "tasks that belong to a task" too. `ON DELETE SET NULL`
matches `related_event_id`'s choice: deleting the parent orphans its
sub-tasks into ordinary top-level tasks rather than cascading the delete,
so ticking off sub-items isn't destroyed by cleaning up the parent.

Revision ID: c0123456789y
Revises: b0123456789x
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c0123456789y"
down_revision: Union[str, None] = "b0123456789x"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "parent_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_parent_task_id", "tasks", ["parent_task_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_constraint("tasks_parent_task_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "parent_task_id")
