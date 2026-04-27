"""add workspace system

Revision ID: c1234567890a
Revises: e8916bf7593a
Create Date: 2026-04-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1234567890a'
down_revision: Union[str, None] = 'e8916bf7593a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create workspaces table
    op.create_table('workspaces',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('owner_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(255), nullable=True, unique=True),
        sa.Column('is_personal', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime, server_default=sa.text('NOW()')),
    )
    op.create_index('ix_workspaces_owner_id', 'workspaces', ['owner_id'])

    # Create workspace_members table
    op.create_table('workspace_members',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=sa.text('gen_random_uuid()')),
        sa.Column('workspace_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, server_default='viewer'),
        sa.Column('invited_by', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('joined_at', sa.DateTime, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('workspace_id', 'user_id', name='uq_workspace_members_workspace_user'),
    )
    op.create_index('ix_workspace_members_workspace', 'workspace_members', ['workspace_id'])
    op.create_index('ix_workspace_members_user', 'workspace_members', ['user_id'])

    # Add workspace_id to notes table (nullable initially)
    op.add_column('notes', sa.Column('workspace_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_notes_workspace_id', 'notes', ['workspace_id'])

    # Add workspace_id to assets table (nullable initially)
    op.add_column('assets', sa.Column('workspace_id', postgresql.UUID(as_uuid=True),
        sa.ForeignKey('workspaces.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_assets_workspace_id', 'assets', ['workspace_id'])


def downgrade() -> None:
    # Remove workspace_id from assets
    op.drop_index('ix_assets_workspace_id', table_name='assets')
    op.drop_column('assets', 'workspace_id')

    # Remove workspace_id from notes
    op.drop_index('ix_notes_workspace_id', table_name='notes')
    op.drop_column('notes', 'workspace_id')

    # Drop workspace_members table
    op.drop_index('ix_workspace_members_user', table_name='workspace_members')
    op.drop_index('ix_workspace_members_workspace', table_name='workspace_members')
    op.drop_table('workspace_members')

    # Drop workspaces table
    op.drop_index('ix_workspaces_owner_id', table_name='workspaces')
    op.drop_table('workspaces')
