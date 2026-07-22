"""add_note_edit_proposals

Revision ID: 1b96f74f73b1
Revises: o0123456789k
Create Date: 2026-07-20 14:10:08.153358

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '1b96f74f73b1'
down_revision: Union[str, None] = 'o0123456789k'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('note_edit_proposals',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('note_id', sa.UUID(), nullable=False),
        sa.Column('base_revision_id', sa.UUID(), nullable=True),
        sa.Column('base_version', sa.Integer(), nullable=False),
        sa.Column('patch', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('creator_type', sa.String(length=20), nullable=False),
        sa.Column('creator_id', sa.String(length=255), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('approved_by', sa.UUID(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('rejected_by', sa.UUID(), nullable=True),
        sa.Column('rejected_at', sa.DateTime(), nullable=True),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('conversation_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['base_revision_id'], ['note_revisions.id'], ),
        sa.ForeignKeyConstraint(['note_id'], ['notes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['rejected_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_note_edit_proposals_note_id'), 'note_edit_proposals', ['note_id'], unique=False)
    op.create_index('ix_proposals_creator', 'note_edit_proposals', ['creator_type', 'creator_id'], unique=False)
    op.create_index('ix_proposals_expires', 'note_edit_proposals', ['status', 'expires_at'], unique=False)
    op.create_index('ix_proposals_note_status', 'note_edit_proposals', ['note_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_proposals_note_status', table_name='note_edit_proposals')
    op.drop_index('ix_proposals_expires', table_name='note_edit_proposals')
    op.drop_index('ix_proposals_creator', table_name='note_edit_proposals')
    op.drop_index(op.f('ix_note_edit_proposals_note_id'), table_name='note_edit_proposals')
    op.drop_table('note_edit_proposals')
