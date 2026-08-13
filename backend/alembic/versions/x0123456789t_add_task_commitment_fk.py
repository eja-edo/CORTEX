"""Add the FK on tasks.related_commitment_id (owed since Milestone 2.4)

`tasks.related_commitment_id` (2.5) was created before `commitments` (2.4)
existed as a table in this codebase's build order, so it was left as a bare
UUID column with a note that the constraint was a one-line migration once
`commitments` landed. `commitments` has existed since v0123456789r; this is
that one line.

`ondelete="SET NULL"`, matching every other `related_*` column on `tasks`:
a task outliving the commitment that spawned it is correct — the work still
needs doing even if the promise behind it is deleted — and CASCADE would
turn "delete a commitment" into "silently delete someone's task".

Revision ID: x0123456789t
Revises: w0123456789s
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "x0123456789t"
down_revision: Union[str, None] = "w0123456789s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_foreign_key(
        "tasks_related_commitment_id_fkey",
        "tasks",
        "commitments",
        ["related_commitment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("tasks_related_commitment_id_fkey", "tasks", type_="foreignkey")
