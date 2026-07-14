"""Drop old memory system tables (replaced by new extraction pipeline)

Revision ID: m9012345678i
Revises: l7890123456h
Create Date: 2026-07-11
"""

from typing import Sequence, Union

from alembic import op


revision: str = "m9012345678i"
down_revision: Union[str, None] = "l7890123456h"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop in reverse dependency order: memory_links and memory_embeddings
    # reference other tables; action_history, knowledge_chunks, etc. are leaf tables.
    op.drop_table("memory_links")
    op.drop_table("memory_embeddings")
    op.drop_table("action_history")
    op.drop_table("knowledge_chunks")
    op.drop_table("episodic_memories")
    op.drop_table("preference_memories")
    op.drop_table("semantic_memories")
    op.drop_table("conversation_summaries")


def downgrade() -> None:
    pass
