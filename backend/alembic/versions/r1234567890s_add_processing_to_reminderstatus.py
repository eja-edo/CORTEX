"""Add processing to reminderstatus enum

`ReminderWorker._process_due_reminders` (refactor_schedule) claims a due
reminder by setting status='processing' before delivering it, so two worker
loops don't send the same reminder twice. `ReminderStatus.PROCESSING` was
added to the Python enum in the same change, but the Postgres enum type was
never altered to match — every due reminder now fails with
`InvalidTextRepresentationError: invalid input value for enum
reminderstatus: "processing"` before it can be sent.

Revision ID: r1234567890s
Revises: cc03noauth1
Create Date: 2026-09-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "r1234567890s"
down_revision: Union[str, None] = "cc03noauth1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # See y0123456789u for why this needs autocommit_block(): Postgres
    # refuses to use a new enum value in the same transaction that added it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE reminderstatus ADD VALUE 'processing'")


def downgrade() -> None:
    # PostgreSQL doesn't support removing enum values. This is a no-op.
    pass
