"""Drop Goal; add tasks.priority and tasks.description

Goal's only real consumer was the "Hôm nay" ranking engine (importance =
which goal a task serves × how close that goal's target date is) and its
"goal deadline near" reason sentence. That signal is replaced by a
user-set `priority` on Task directly, combined with `due_date` — see
`app.services.today`. `description` is added alongside it so a task (in
particular one created as an event's checklist/subtask item) can carry more
than a bare title.

Three things, in order, so nothing dangles mid-migration:

1. Drop `tasks.related_goal_id` (FK + `ix_tasks_related_goal_id_status`).
2. Drop `goals` (+ its two indexes) and the `goalstatus` enum.
3. Add `tasks.priority` (new `taskpriority` enum, nullable — unset means
   "no priority") and `tasks.description` (Text, nullable).

Irreversible by construction, same as `a0123456789w`: reversing step 1-2
would mean restoring an empty `goals` table that disagrees with whatever
`tasks` looks like by the time anyone runs `downgrade()` — worse than
refusing outright.

Revision ID: b0123456789x
Revises: a0123456789w
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b0123456789x"
down_revision: Union[str, None] = "a0123456789w"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

goalstatus_enum = postgresql.ENUM(
    "active", "achieved", "abandoned", "paused", name="goalstatus"
)
taskpriority_enum = postgresql.ENUM(
    "low", "medium", "high", "urgent", name="taskpriority"
)


def upgrade() -> None:
    # 1. tasks.related_goal_id
    op.drop_index("ix_tasks_related_goal_id_status", table_name="tasks")
    op.drop_constraint("tasks_related_goal_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "related_goal_id")

    # 2. goals
    op.drop_index("ix_goals_user_status_target_date", table_name="goals")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
    goalstatus_enum.drop(op.get_bind(), checkfirst=True)

    # 3. tasks.priority / tasks.description
    taskpriority_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "tasks",
        sa.Column(
            "priority",
            postgresql.ENUM("low", "medium", "high", "urgent", name="taskpriority", create_type=False),
            nullable=True,
        ),
    )
    op.add_column("tasks", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "This migration drops `goals` after its only consumer (Today's "
        "ranking) moved to a plain `tasks.priority` column. Reversing it "
        "would mean restoring an empty `goals` table that no longer "
        "agrees with what `tasks` holds, or fabricating goal rows that "
        "were never there — both are worse than refusing. Restore from a "
        "backup taken before this migration ran."
    )
