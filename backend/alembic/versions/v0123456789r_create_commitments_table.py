"""Create commitments table (Milestone 2.4 — Commitment Data Model)

The 13 columns 2.4 fixes:
{id, user_id, direction, counterparty, expected_action, deadline, status,
 related_goal_id, related_task_id, source_conversation_id, source_message_id,
 created_at, confirmed_at}.

`direction` is the load-bearing field. `user_id` is always the account
holder, `counterparty` always the other side; direction says which way the
obligation runs. The old `owner`/`subject_person` pair is deliberately not
used — it never said which of the two was the account holder, so it couldn't
answer "who is waiting on me?", the question the whole feature exists for.

No stored fingerprint column for rejected candidates. The fingerprint is
derived from `counterparty` + `expected_action`, both of which are already
here, so storing a hash would be a second source of truth that can disagree
with the text it hashes. What 2.3 needs is the lookup to be fast, which the
expression index below provides — see app/services/commitments.py.

No `workspace_id`: promises are personal in Phase 2.

Revision ID: v0123456789r
Revises: u0123456789q
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "v0123456789r"
down_revision: Union[str, None] = "u0123456789q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

direction_enum = postgresql.ENUM("i_owe", "owed_to_me", name="commitmentdirection")
status_enum = postgresql.ENUM(
    "pending_confirm", "active", "fulfilled", "cancelled", "rejected",
    name="commitmentstatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    direction_enum.create(bind, checkfirst=True)
    status_enum.create(bind, checkfirst=True)

    op.create_table(
        "commitments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "direction",
            postgresql.ENUM("i_owe", "owed_to_me", name="commitmentdirection", create_type=False),
            nullable=False,
        ),
        # Raw string, unnormalised on purpose — Person entity is Phase 5.
        sa.Column("counterparty", sa.String(255), nullable=False),
        sa.Column("expected_action", sa.Text(), nullable=False),
        sa.Column("deadline", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "pending_confirm", "active", "fulfilled", "cancelled", "rejected",
                name="commitmentstatus", create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pending_confirm'"),
        ),
        # SET NULL everywhere: a commitment outliving its goal, its task or
        # the conversation it came from is correct — the promise still
        # stands, it just lost context. CASCADE would delete real obligations
        # as a side effect of tidying up a conversation.
        sa.Column(
            "related_goal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("goals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "related_task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "source_message_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )

    op.create_index("ix_commitments_user_id", "commitments", ["user_id"])
    op.create_index("ix_commitments_source_conversation_id", "commitments", ["source_conversation_id"])
    # 6.7/6.8: "what's active, which way does it run, when is it due?"
    op.create_index(
        "ix_commitments_user_status_direction_deadline",
        "commitments",
        ["user_id", "status", "direction", "deadline"],
    )
    # 2.3: "did the user already reject this exact promise?" — matches the
    # normalisation in app/services/commitments.py exactly, or it won't be used.
    op.execute(
        "CREATE INDEX ix_commitments_user_status_content ON commitments "
        "(user_id, status, lower(btrim(counterparty)), lower(btrim(expected_action)))"
    )


def downgrade() -> None:
    op.drop_index("ix_commitments_user_status_content", table_name="commitments")
    op.drop_index("ix_commitments_user_status_direction_deadline", table_name="commitments")
    op.drop_index("ix_commitments_source_conversation_id", table_name="commitments")
    op.drop_index("ix_commitments_user_id", table_name="commitments")
    op.drop_table("commitments")

    bind = op.get_bind()
    status_enum.drop(bind, checkfirst=True)
    direction_enum.drop(bind, checkfirst=True)
