"""Add is_cancelled to tasks

A checklist item's "delete" used to only mean "delete the template,
everywhere" — there was no way to remove one just for a single occurrence of
a recurring event's checklist, unlike `Schedule` (which already has
`is_cancelled` for exactly this: cancelling one instance without touching the
series). This mirrors that column onto `Task` so a `this_only` delete can
create/mark a per-occurrence exception row as cancelled instead of deleting
the shared template — see `TaskService.cancel_task_occurrence`.

Revision ID: s2345678901t
Revises: r1234567890s
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "s2345678901t"
down_revision: Union[str, None] = "r1234567890s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("is_cancelled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("tasks", "is_cancelled")
