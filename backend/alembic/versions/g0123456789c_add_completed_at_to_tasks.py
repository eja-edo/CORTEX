"""Add completed_at to tasks

The timestamp of a task's last transition *into* `done`, cleared the moment
it leaves `done` again. Distinct from `updated_at`, which also moves on an
unrelated edit. Backfilled from `updated_at` for rows already `done` so
existing completions don't all read as "done today" — they just won't show
up in "Hôm nay" again until re-touched, same as a task done any other day.

Revision ID: g0123456789c
Revises: f0123456789b
Create Date: 2026-08-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g0123456789c"
down_revision: Union[str, None] = "f0123456789b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE tasks SET completed_at = updated_at WHERE status = 'done'")


def downgrade() -> None:
    op.drop_column("tasks", "completed_at")
