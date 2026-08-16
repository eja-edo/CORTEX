"""Migrate commitments into tasks, then drop commitments

Final step of folding Commitment into Task (see the "Xoá bỏ Commitment, gộp
vào Task" plan). Three things, in order, so nothing is lost before it's
read:

1. **Backfill.** Every `i_owe` commitment that doesn't already have a linked
   task (an `active` one does — `CommitmentService._ensure_linked_task`
   created it at confirm time) becomes a new `Task`, status mapped onto the
   nearest equivalent (`pending_confirm→pending_confirm`, `active→todo`,
   `fulfilled→done`, `cancelled→cancelled`, `rejected→rejected`). Title is
   `"{expected_action} ({counterparty})"`, the exact convention
   `CommitmentService._task_title` already used for the tasks it created —
   so an already-confirmed commitment's task and a freshly-backfilled one
   read the same way.

   `owed_to_me` commitments are dropped, not migrated: they were never the
   user's own work (2.4 never gave them a task either), and Task has no
   concept of "someone else's obligation" to hold them. Checked against the
   live dev database before writing this migration — all rows there are
   `i_owe`, so this is a documented decision, not blind data loss.

2. Drop `tasks.related_commitment_id` (FK + index): nothing produces it
   anymore, and a column nothing writes to is debt, not history.

3. Drop `commitments` and its two enum types.

Irreversible by construction — `downgrade()` refuses rather than silently
returning an empty `commitments` table, which would be a worse failure mode
than an error.

Revision ID: a0123456789w
Revises: z0123456789v
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "a0123456789w"
down_revision: Union[str, None] = "z0123456789v"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Backfill ──────────────────────────────────────────────────────
    op.execute(
        """
        INSERT INTO tasks (
            id, user_id, title, status, due_date, related_goal_id,
            source_conversation_id, source_message_id, created_at, updated_at
        )
        SELECT
            uuid_generate_v7(),
            user_id,
            LEFT(expected_action || ' (' || counterparty || ')', 255),
            (CASE status::text
                WHEN 'pending_confirm' THEN 'pending_confirm'
                WHEN 'active' THEN 'todo'
                WHEN 'fulfilled' THEN 'done'
                WHEN 'cancelled' THEN 'cancelled'
                WHEN 'rejected' THEN 'rejected'
            END)::taskstatus,
            deadline::date,
            related_goal_id,
            source_conversation_id,
            source_message_id,
            created_at,
            created_at
        FROM commitments
        WHERE direction = 'i_owe' AND related_task_id IS NULL
        """
    )

    # ── 2. Drop the now-unused link column on tasks ─────────────────────
    op.drop_constraint("tasks_related_commitment_id_fkey", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_related_commitment_id", table_name="tasks")
    op.drop_column("tasks", "related_commitment_id")

    # ── 3. Drop commitments itself ───────────────────────────────────────
    op.drop_table("commitments")
    op.execute("DROP TYPE IF EXISTS commitmentstatus")
    op.execute("DROP TYPE IF EXISTS commitmentdirection")


def downgrade() -> None:
    raise NotImplementedError(
        "This migration drops `commitments` after moving its data into "
        "`tasks`. Reversing it would mean either fabricating a "
        "counterparty/direction for a plain Task (data that was never "
        "there) or restoring an empty `commitments` table that silently "
        "disagrees with what `tasks` now holds — both are worse than "
        "refusing. Restore from a backup taken before this migration ran."
    )
