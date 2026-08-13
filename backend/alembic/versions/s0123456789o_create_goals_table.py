"""Create goals table (Milestone 2.1a — Goal tối thiểu)

Exactly the 7 columns the planning doc fixes for 2.1a:
{id, user_id, title, status, target_date, description, created_at, updated_at}.

Explicitly NOT here, each deferred on purpose (see the "Không làm trong
Phase 2" table):
  - `progress`: derived at query time from related tasks (2.2), never stored.
  - `workspace_id`: goals are personal in Phase 2.
  - `related_project_id`: no Project table exists; an FK to nothing is debt.
  - `why` / `goal_milestones`: 2.1b, shipped with 3.2 when the AI Planner
    tells us what it actually consumes.

`goalstatus` is created as a native Postgres enum rather than VARCHAR — see
r0123456789n for why that matters: asyncpg binds enum columns with an
explicit `::goalstatus` cast, and all the async command/API code that writes
goals would fail against a varchar column.

Revision ID: s0123456789o
Revises: r0123456789n
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "s0123456789o"
down_revision: Union[str, None] = "r0123456789n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

goalstatus_enum = postgresql.ENUM(
    "active", "achieved", "abandoned", "paused", name="goalstatus"
)


def upgrade() -> None:
    goalstatus_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "goals",
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
            # create_type=False: the enum was already created above; letting
            # create_table emit its own CREATE TYPE would fail on re-run.
            postgresql.ENUM(
                "active", "achieved", "abandoned", "paused",
                name="goalstatus", create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
    )

    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    # The Attention Gate query shape (6.1 / 6.8): one user's active goals,
    # ordered by target_date.
    op.create_index(
        "ix_goals_user_status_target_date", "goals", ["user_id", "status", "target_date"]
    )


def downgrade() -> None:
    op.drop_index("ix_goals_user_status_target_date", table_name="goals")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
    goalstatus_enum.drop(op.get_bind(), checkfirst=True)
