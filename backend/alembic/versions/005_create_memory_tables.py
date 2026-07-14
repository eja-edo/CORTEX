"""create memory system tables

Revision ID: 005
Revises: 004
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TEXT, TIMESTAMP, BOOLEAN, INTEGER, VARCHAR, FLOAT
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    from dataclasses import dataclass
    @dataclass
    class Vector:
        pass


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── conversation_summaries (Layer 2) ──────────────────────────────────────
    op.create_table('conversation_summaries',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('conversation_id', UUID(as_uuid=True), sa.ForeignKey('agent_conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('summary_text', sa.Text, nullable=False),
        sa.Column('summary_version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('message_start_id', UUID(as_uuid=True), nullable=True),
        sa.Column('message_end_id', UUID(as_uuid=True), nullable=True),
        sa.Column('message_count', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('model_used', sa.String(100), nullable=True),
        sa.Column('tokens_used', sa.Integer, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('previous_summary_id', UUID(as_uuid=True), nullable=True),
    )
    op.create_index('idx_conv_summaries_conv_version', 'conversation_summaries', ['conversation_id', 'summary_version'])
    op.create_index('idx_conv_summaries_user', 'conversation_summaries', ['user_id'])

    # ── semantic_memories (Layer 3) ───────────────────────────────────────────
    op.create_table('semantic_memories',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('workspace_id', UUID(as_uuid=True), nullable=True),
        sa.Column('memory_type', sa.String(50), nullable=False),
        sa.Column('subject', sa.String(200), nullable=False),
        sa.Column('value', sa.Text, nullable=False),
        sa.Column('confidence_score', sa.Float, nullable=False, server_default=sa.text('0.8')),
        sa.Column('importance_score', sa.Float, nullable=False, server_default=sa.text('0.5')),
        sa.Column('memory_class', sa.String(20), nullable=False),
        sa.Column('source_message_id', UUID(as_uuid=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('tags', sa.ARRAY(sa.String), server_default=sa.text("'{}'")),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_semantic_user_active', 'semantic_memories', ['user_id', 'is_active'])
    op.create_index('idx_semantic_subject', 'semantic_memories', ['subject', 'user_id'])
    op.create_index('idx_semantic_type', 'semantic_memories', ['memory_type', 'user_id'])
    op.create_index('idx_semantic_expires', 'semantic_memories', ['expires_at'],
                    postgresql_where=sa.text('expires_at IS NOT NULL'))

    # ── preference_memories (Layer 4) ─────────────────────────────────────────
    op.create_table('preference_memories',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('category', sa.String(100), nullable=False),
        sa.Column('key', sa.String(200), nullable=False),
        sa.Column('value', sa.Text, nullable=False),
        sa.Column('confidence_score', sa.Float, nullable=False, server_default=sa.text('0.8')),
        sa.Column('evidence_count', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('last_evidenced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decay_rate', sa.Float, nullable=False, server_default=sa.text('0.1')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.UniqueConstraint('user_id', 'category', 'key', name='uq_pref_user_category_key'),
    )
    op.create_index('idx_pref_user_id', 'preference_memories', ['user_id'])
    op.create_index('idx_pref_category', 'preference_memories', ['user_id', 'category'])
    op.create_index('idx_pref_confidence', 'preference_memories', ['user_id', 'confidence_score'])

    # ── episodic_memories (Layer 5) ───────────────────────────────────────────
    op.create_table('episodic_memories',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_title', sa.String(300), nullable=False),
        sa.Column('event_summary', sa.Text, nullable=False),
        sa.Column('importance_score', sa.Float, nullable=False, server_default=sa.text('0.5')),
        sa.Column('related_entities', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('occurrence_count', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('source_conversation_ids', JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column('tags', sa.ARRAY(sa.String), server_default=sa.text("'{}'")),
    )
    op.create_index('idx_episodic_user_active', 'episodic_memories', ['user_id', 'is_active'])
    op.create_index('idx_episodic_entities', 'episodic_memories', ['related_entities'],
                    postgresql_using='gin')
    op.create_index('idx_episodic_last_seen', 'episodic_memories', ['user_id', 'last_seen_at'])
    op.create_index('idx_episodic_type', 'episodic_memories', ['user_id', 'event_type'])

    # ── knowledge_chunks (Layer 6) ────────────────────────────────────────────
    op.create_table('knowledge_chunks',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(50), nullable=False),
        sa.Column('source_id', UUID(as_uuid=True), nullable=True),
        sa.Column('chunk_index', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('chunk_text', sa.Text, nullable=False),
        sa.Column('embedding', Vector(768), nullable=True),
        sa.Column('metadata', JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
    )
    op.create_index('idx_knowledge_user_source', 'knowledge_chunks', ['user_id', 'source_type', 'is_active'])
    op.create_index('idx_knowledge_entity', 'knowledge_chunks', ['source_type', 'source_id'])
    op.create_index('idx_knowledge_expires', 'knowledge_chunks', ['expires_at'],
                    postgresql_where=sa.text('expires_at IS NOT NULL'))

    # ── action_history (Layer 7) ──────────────────────────────────────────────
    op.create_table('action_history',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('conversation_id', UUID(as_uuid=True), nullable=True),
        sa.Column('tool_name', sa.String(100), nullable=False),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('action_id', sa.String(100), nullable=True),
        sa.Column('before_state', JSONB, nullable=True),
        sa.Column('after_state', JSONB, nullable=True),
        sa.Column('is_reverted', sa.Boolean, nullable=False, server_default=sa.text('false')),
        sa.Column('reverted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_action_user_time', 'action_history', ['user_id', sa.text('created_at DESC')])
    op.create_index('idx_action_tool', 'action_history', ['tool_name', sa.text('created_at DESC')])
    op.create_index('idx_action_unreverted', 'action_history', ['user_id', 'is_reverted'],
                    postgresql_where=sa.text("is_reverted = FALSE"))

    # ── memory_links ──────────────────────────────────────────────────────────
    op.create_table('memory_links',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('source_id', UUID(as_uuid=True), nullable=False),
        sa.Column('target_type', sa.String(30), nullable=False),
        sa.Column('target_id', UUID(as_uuid=True), nullable=False),
        sa.Column('relationship', sa.String(50), nullable=False),
        sa.Column('strength', sa.Float, nullable=False, server_default=sa.text('0.5')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.UniqueConstraint('source_type', 'source_id', 'target_type', 'target_id', 'relationship',
                           name='uq_memory_links'),
    )
    op.create_index('idx_memory_links_source', 'memory_links', ['source_type', 'source_id'])
    op.create_index('idx_memory_links_target', 'memory_links', ['target_type', 'target_id'])

    # ── memory_embeddings (polymorphic, for semantic/episodic) ─────────────────
    op.create_table('memory_embeddings',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('user_id', UUID(as_uuid=True), nullable=False),
        sa.Column('memory_type', sa.String(30), nullable=False),
        sa.Column('memory_id', UUID(as_uuid=True), nullable=False),
        sa.Column('embedding', Vector(768), nullable=False),
        sa.Column('source_text', sa.Text, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()')),
        sa.UniqueConstraint('memory_type', 'memory_id', name='uq_memory_embeddings_unique'),
    )
    op.create_index('idx_memory_embeddings_user_type', 'memory_embeddings', ['user_id', 'memory_type'])

    # ── Add indexes to existing agent_messages ─────────────────────────────────
    op.create_index('idx_agent_messages_token_count', 'agent_messages',
                    ['conversation_id', 'token_count'],
                    postgresql_where=sa.text('token_count IS NOT NULL'))


def downgrade() -> None:
    op.drop_table('memory_embeddings')
    op.drop_table('memory_links')
    op.drop_table('action_history')
    op.drop_table('knowledge_chunks')
    op.drop_table('episodic_memories')
    op.drop_table('preference_memories')
    op.drop_table('semantic_memories')
    op.drop_table('conversation_summaries')
    op.drop_index('idx_agent_messages_token_count', table_name='agent_messages', if_exists=True)
