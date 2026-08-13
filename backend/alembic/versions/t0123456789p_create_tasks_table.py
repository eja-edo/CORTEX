"""Create tasks table (Milestone 2.5 — Task Data Model)

The 10 columns 2.5 fixes:
{id, user_id, title, status, due_date, related_goal_id, related_event_id,
 related_commitment_id, created_at, updated_at}.

Deliberately absent:
  - `priority`: importance is derived from `related_goal_id` + the goal's
    target_date, never entered by the user (2.5 "Lưu ý thiết kế 1" / M5).
  - `related_project_id`: 2.5's description mentions it, but Phase 2's
    "Không làm" table defers the Project entity — no table to point at.
  - `start_time`/`end_time`: a task consumes time, it doesn't occupy it.
    That's the whole reason this isn't a row in `schedules`.

FK delete behavior is SET NULL on both real FKs, not the default RESTRICT:
`goals` and `schedules` are both hard-deleted by their services, so RESTRICT
would turn "delete this goal" into an IntegrityError as soon as one task
points at it. A task outliving its goal or its event is the correct outcome —
the work still needs doing, it just lost its context. CASCADE would be worse
still: deleting a meeting would silently destroy its checklist.

`related_commitment_id` carries no FK yet — `commitments` arrives in 2.4.

Revision ID: t0123456789p
Revises: s0123456789o
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "t0123456789p"
down_revision: Union[str, None] = "s0123456789o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

taskstatus_enum = postgresql.ENUM(
    "todo", "in_progress", "done", "cancelled", name="taskstatus"
)


def upgrade() -> None:
    taskstatus_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column(
            "status",
            # create_type=False: created above; letting create_table emit its
            # own CREATE TYPE would fail on re-run.
            postgresql.ENUM(
                "todo", "in_progress", "done", "cancelled",
                name="taskstatus", create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'todo'"),
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column(
            "related_goal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "related_event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("related_commitment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_index("ix_tasks_user_id", "tasks", ["user_id"])
    # Required by 2.2 M1: goal progress is COUNT(done)/COUNT(*) over this pair.
    op.create_index("ix_tasks_related_goal_id_status", "tasks", ["related_goal_id", "status"])
    op.create_index("ix_tasks_related_event_id", "tasks", ["related_event_id"])
    op.create_index("ix_tasks_related_commitment_id", "tasks", ["related_commitment_id"])
    op.create_index("ix_tasks_user_status_due_date", "tasks", ["user_id", "status", "due_date"])


def downgrade() -> None:
    op.drop_index("ix_tasks_user_status_due_date", table_name="tasks")
    op.drop_index("ix_tasks_related_commitment_id", table_name="tasks")
    op.drop_index("ix_tasks_related_event_id", table_name="tasks")
    op.drop_index("ix_tasks_related_goal_id_status", table_name="tasks")
    op.drop_index("ix_tasks_user_id", table_name="tasks")
    op.drop_table("tasks")
    taskstatus_enum.drop(op.get_bind(), checkfirst=True)
