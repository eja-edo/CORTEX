"""add pgvector and note embeddings

Revision ID: g2345678901c
Revises: f1234567890b
Create Date: 2026-05-05 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'g2345678901c'
down_revision: Union[str, None] = 'f1234567890b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # Create pgvector extension (idempotent)
        op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        
        # Add embedding column to notes table using raw SQL for vector type
        # pgvector doesn't have a native SQLAlchemy type, so we use raw SQL
        op.execute(
            "ALTER TABLE notes ADD COLUMN embedding vector(768) NULL;"
        )
        
        # Add embedding_generated_at to track when embedding was computed
        op.add_column(
            'notes',
            sa.Column('embedding_generated_at', sa.DateTime, nullable=True),
        )
        
        # Create ivfflat index for semantic similarity search
        # CONCURRENTLY allows the index to be built without blocking writes
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notes_embedding ON notes "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        # Drop index
        op.execute("DROP INDEX IF EXISTS ix_notes_embedding;")
        
        # Drop columns
        op.drop_column('notes', 'embedding_generated_at')
        op.execute("ALTER TABLE notes DROP COLUMN IF EXISTS embedding;")
        
        # Note: We don't drop the pgvector extension in downgrade to avoid
        # breaking other potential uses. In production, coordinate with DBAs.
