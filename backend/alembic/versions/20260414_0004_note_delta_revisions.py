"""note delta revisions

Revision ID: 20260414_0004
Revises: 20260413_0003
Create Date: 2026-04-14 09:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260414_0004"
down_revision: Union[str, None] = "20260413_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column("checkpoint_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )

    op.create_table(
        "note_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("patch", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("patch_format", sa.String(length=32), nullable=False, server_default=sa.text("'text_diff'")),
        sa.Column("content_length", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "version", name="uq_note_revisions_note_version"),
    )
    op.create_index("ix_note_revisions_note_id", "note_revisions", ["note_id"], unique=False)
    op.create_index("ix_note_revisions_user_id", "note_revisions", ["user_id"], unique=False)
    op.create_index("ix_note_revisions_note_id_version", "note_revisions", ["note_id", "version"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_note_revisions_note_id_version", table_name="note_revisions")
    op.drop_index("ix_note_revisions_user_id", table_name="note_revisions")
    op.drop_index("ix_note_revisions_note_id", table_name="note_revisions")
    op.drop_table("note_revisions")

    op.drop_column("notes", "checkpoint_version")
