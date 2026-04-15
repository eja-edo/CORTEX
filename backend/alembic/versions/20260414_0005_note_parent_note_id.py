"""note parent hierarchy

Revision ID: 20260414_0005
Revises: 20260414_0004
Create Date: 2026-04-14 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260414_0005"
down_revision: Union[str, None] = "20260414_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "notes",
        sa.Column("parent_note_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_notes_parent_note_id_notes",
        "notes",
        "notes",
        ["parent_note_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_notes_parent_note_id", "notes", ["parent_note_id"], unique=False)
    op.create_index("ix_notes_user_parent_updated_at", "notes", ["user_id", "parent_note_id", "updated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_notes_user_parent_updated_at", table_name="notes")
    op.drop_index("ix_notes_parent_note_id", table_name="notes")
    op.drop_constraint("fk_notes_parent_note_id_notes", "notes", type_="foreignkey")
    op.drop_column("notes", "parent_note_id")