"""remove segments, note links, ingest jobs tables

Revision ID: 20260422_0007
Revises: 20260416_0006
Create Date: 2026-04-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260422_0007"
down_revision: Union[str, None] = "20260416_0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.drop_table("bookmarks")
    op.drop_table("entity_tags")
    op.drop_table("segment_embeddings")
    op.drop_table("note_embeddings")
    op.drop_table("segment_contents")
    op.drop_table("note_segment_links")
    op.drop_table("segments")
    op.drop_table("ingest_jobs")

def downgrade() -> None:
    # Downgrade logic would need to recreate the tables, omitted for brevity
    pass