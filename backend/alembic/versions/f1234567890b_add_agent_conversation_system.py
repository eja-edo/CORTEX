"""add agent conversation system

Revision ID: f1234567890b
Revises: d234567890ab
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1234567890b'
down_revision: Union[str, None] = 'd234567890ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create agent_conversations table
    op.create_table('agent_conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v7()')),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('ix_agent_conversations_user_id', 'agent_conversations', ['user_id'])
    op.create_index('ix_agent_conversations_user_created', 'agent_conversations', ['user_id', 'created_at'])
    op.create_index('ix_agent_conversations_workspace_id', 'agent_conversations', ['workspace_id'])

    # Create agent_messages table
    op.create_table('agent_messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('uuid_generate_v7()')),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('agent_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False),
        sa.Column('content', sa.Text, nullable=True),
        sa.Column('tool_name', sa.String(100), nullable=True),
        sa.Column('tool_input', postgresql.JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column('tool_output', postgresql.JSONB, nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column('token_count', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime, nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_index('ix_agent_messages_conversation_created', 'agent_messages', ['conversation_id', 'created_at'])
    op.create_index('ix_agent_messages_conversation_role', 'agent_messages', ['conversation_id', 'role'])


def downgrade() -> None:
    op.drop_index('ix_agent_messages_conversation_role', 'agent_messages')
    op.drop_index('ix_agent_messages_conversation_created', 'agent_messages')
    op.drop_table('agent_messages')
    
    op.drop_index('ix_agent_conversations_workspace_id', 'agent_conversations')
    op.drop_index('ix_agent_conversations_user_created', 'agent_conversations')
    op.drop_index('ix_agent_conversations_user_id', 'agent_conversations')
    op.drop_table('agent_conversations')
