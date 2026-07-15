"""Add title column to notes table

Revision ID: n9012345678j
Revises: m9012345678i
Create Date: 2026-07-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import re


revision: str = "n9012345678j"
down_revision: Union[str, None] = "m9012345678i"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def extract_title(content: str) -> str:
    for line in content.split("\n"):
        text = re.sub(r"^#+\s*", "", line).strip()
        if text:
            return text[:500]
    return "Untitled"


def upgrade() -> None:
    op.add_column("notes", sa.Column("title", sa.String(500), nullable=True))

    conn = op.get_bind()
    notes = conn.execute(sa.text("SELECT id, content FROM notes")).fetchall()
    for note_id, content in notes:
        title = extract_title(content) if content else "Untitled"
        conn.execute(
            sa.text("UPDATE notes SET title = :title WHERE id = :id"),
            {"title": title, "id": note_id},
        )

    op.alter_column("notes", "title", nullable=False)


def downgrade() -> None:
    op.drop_column("notes", "title")
