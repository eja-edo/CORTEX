"""Fix workspace_members.role: create missing workspacerole enum type

The original migration (c1234567890a_add_workspace_system) created this
column as plain VARCHAR(20), but app/models.py has always declared it as
SQLEnum(WorkspaceRole, name="workspacerole") — the same pattern used by
every other enum column in this schema (assettype, remindermethod,
scheduletype, ...), all of which DO have a matching native Postgres enum
type. workspacerole never did.

This is invisible to sync (psycopg2) callers, which bind the value as a
plain string and let Postgres implicitly accept it into the varchar
column. It breaks async (asyncpg) callers, which the asyncpg dialect
binds with an explicit `::workspacerole` type cast — failing with
"type workspacerole does not exist" for any INSERT. All new Phase 1
AI/command code is async-only, so this needed fixing before it becomes a
landmine for the next feature that creates workspace members from that
path.

Revision ID: r0123456789n
Revises: q0123456789m
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "r0123456789n"
down_revision: Union[str, None] = "q0123456789m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

workspacerole_enum = postgresql.ENUM("owner", "editor", "viewer", name="workspacerole")


def upgrade() -> None:
    workspacerole_enum.create(op.get_bind(), checkfirst=True)
    # Postgres can't cast the existing VARCHAR default to the new enum type
    # in the same ALTER — drop it first, convert the column, then reattach.
    op.execute("ALTER TABLE workspace_members ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE workspace_members "
        "ALTER COLUMN role TYPE workspacerole USING role::workspacerole"
    )
    op.execute("ALTER TABLE workspace_members ALTER COLUMN role SET DEFAULT 'viewer'::workspacerole")


def downgrade() -> None:
    op.execute("ALTER TABLE workspace_members ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE workspace_members "
        "ALTER COLUMN role TYPE VARCHAR(20) USING role::text"
    )
    op.execute("ALTER TABLE workspace_members ALTER COLUMN role SET DEFAULT 'viewer'")
    workspacerole_enum.drop(op.get_bind(), checkfirst=True)
