"""add HNSW indexes for pgvector

Revision ID: 006
Revises: 005
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_knowledge_embedding_hnsw
        ON knowledge_chunks
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_memory_embeddings_hnsw
        ON memory_embeddings
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_notes_embedding_hnsw
        ON notes
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)


def downgrade() -> None:
    op.execute('DROP INDEX IF EXISTS idx_knowledge_embedding_hnsw')
    op.execute('DROP INDEX IF EXISTS idx_memory_embeddings_hnsw')
    op.execute('DROP INDEX IF EXISTS idx_notes_embedding_hnsw')
