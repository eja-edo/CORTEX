"""Add pending_confirm/rejected to taskstatus enum

Commitment is being folded into Task (see the "Xoá bỏ Commitment, gộp vào
Task" plan): a task extracted from a conversation is a guess the AI makes,
so it needs a human yes/no before it counts as real work — the same reason
`CommitmentStatus.PENDING_CONFIRM`/`REJECTED` existed. Every other creation
path (typed directly, a goal breakdown, an event checklist) starts at
`todo`, so these two values are additive, not a change to existing rows.

Revision ID: y0123456789u
Revises: x0123456789t
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op


revision: str = "y0123456789u"
down_revision: Union[str, None] = "x0123456789t"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres refuses to use a new enum value in the same transaction that
    # added it ("unsafe use of new value... must be committed before they
    # can be used") — and this repo's env.py wraps the whole `alembic
    # upgrade head` run in one transaction (no `transaction_per_migration`),
    # so a later migration in the same run (the commitments→tasks backfill)
    # would hit exactly that error without this. `autocommit_block()`
    # commits these two statements immediately, outside the ambient
    # transaction, so the value is safely visible to migrations after this
    # one in the same run.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE taskstatus ADD VALUE 'pending_confirm'")
        op.execute("ALTER TYPE taskstatus ADD VALUE 'rejected'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values. This is a no-op.
    pass
