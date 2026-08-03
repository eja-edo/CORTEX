"""create semantic_memories table for pgvector-based semantic memory

Revision ID: p0123456789l
Revises: o0123456789k
Create Date: 2026-07-29

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision: str = "p0123456789l"
down_revision: Union[str, None] = "1b96f74f73b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table("semantic_memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        # NOTE: "user_id" currently holds workspace_id (str), matching how
        #       ZepMemoryService uses the "user_id" parameter. Memory is
        #       scoped per workspace, not per individual user.
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("category", sa.String(30), nullable=False),  # project|preference|constraint|environment|decision_pattern
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("confidence", sa.Float, nullable=False, server_default=sa.text("0.8")),
        sa.Column("expected_lifetime", sa.String(20), nullable=False, server_default=sa.text("'medium'")),  # short|medium|long|permanent
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.Column("source_metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )

    op.create_index("idx_semantic_memories_user", "semantic_memories", ["user_id"])
    op.create_index(
        "idx_semantic_memories_hnsw",
        "semantic_memories",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("idx_semantic_memories_hnsw", table_name="semantic_memories", if_exists=True)
    op.drop_index("idx_semantic_memories_user", table_name="semantic_memories", if_exists=True)
    op.drop_table("semantic_memories")
