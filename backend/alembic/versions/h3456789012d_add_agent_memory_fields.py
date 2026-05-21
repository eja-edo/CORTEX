"""add agent memory and token tracking fields

Revision ID: h3456789012d
Revises: g2345678901c
Create Date: 2026-05-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h3456789012d'
down_revision: Union[str, None] = 'g2345678901c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Add memory and token tracking fields to agent_conversations table.
    
    These fields enable:
    - Conversation summarization (summary column)
    - Message count tracking for deciding when to summarize (message_count)
    - Token budget control (total_token_count)
    """
    # Add summary column for storing compressed conversation context
    op.add_column(
        'agent_conversations',
        sa.Column('summary', sa.Text, nullable=True),
    )
    
    # Add message_count to track total messages in conversation
    op.add_column(
        'agent_conversations',
        sa.Column('message_count', sa.Integer, nullable=False, server_default='0'),
    )
    
    # Add total_token_count for token budget control
    op.add_column(
        'agent_conversations',
        sa.Column('total_token_count', sa.Integer, nullable=False, server_default='0'),
    )


def downgrade() -> None:
    """Remove memory and token tracking fields."""
    op.drop_column('agent_conversations', 'total_token_count')
    op.drop_column('agent_conversations', 'message_count')
    op.drop_column('agent_conversations', 'summary')
