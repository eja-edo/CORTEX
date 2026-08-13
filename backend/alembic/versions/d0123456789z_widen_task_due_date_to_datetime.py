"""Widen tasks.due_date from Date to DateTime (no timezone)

A task's deadline is still a day by default, not a booked span — nothing
about the Task/Schedule boundary changes. What changes is that a time can
now optionally ride along: the first consumer is 2.6's event checklist,
where a subtask created inside an event defaults its deadline to that
event's own `end_time` down to the minute, not just the day. A plain task
created with a bare date still lands at midnight, same as before.

Deliberately **not** `TIMESTAMPTZ`, unlike `schedules.start_time`/`end_time`.
A due date is the user's own wall-clock fact ("done by 3pm my time"), not a
real-world instant shared across zones — same reasoning the calendar feed
already applies when reading it back (`parseServerDay` reads the literal
Y-M-D rather than reinterpreting through a timezone). A `TIMESTAMPTZ` column
would tempt exactly that reinterpretation, and it actually broke on this
build: asyncpg encodes a naive Python `datetime` bound to a `TIMESTAMPTZ`
column using the *client machine's* local zone, not the Postgres session's —
so a plain `date(2026, 10, 14)` came back as `2026-10-13 17:00:00+00:00` on
a UTC+7 box. `TIMESTAMP` (no tz) stores exactly the wall-clock value handed
to it, with no conversion in either direction, matching how `Date` already
behaved.

`USING due_date::timestamp` reinterprets each existing date as midnight of
that same day — a plain type widening, not a timezone conversion, so no
existing row's calendar day changes.

Revision ID: d0123456789z
Revises: c0123456789y
Create Date: 2026-08-08
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d0123456789z"
down_revision: Union[str, None] = "c0123456789y"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN due_date TYPE TIMESTAMP USING due_date::timestamp"
    )


def downgrade() -> None:
    # Lossy on purpose: any time-of-day a row picked up after this migration
    # ran is truncated back to a bare day, same as before this migration.
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN due_date TYPE DATE USING due_date::date"
    )
