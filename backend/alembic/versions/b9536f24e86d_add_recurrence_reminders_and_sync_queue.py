"""add recurrence, reminders, and sync queue

Revision ID: b9536f24e86d
Revises: a8425e13d75c
Create Date: 2026-04-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b9536f24e86d'
down_revision: Union[str, None] = 'a8425e13d75c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add recurrence and versioning columns to schedules
    op.add_column('schedules', sa.Column('recurrence_rule', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('schedules', sa.Column('recurrence_id', sa.UUID(), nullable=True))
    op.add_column('schedules', sa.Column('original_start_time', sa.DateTime(timezone=True), nullable=True))
    op.add_column('schedules', sa.Column('is_exception', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('schedules', sa.Column('is_cancelled', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('schedules', sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False))
    op.add_column('schedules', sa.Column('updated_by', sa.String(length=20), server_default=sa.text("'INTERNAL'"), nullable=False))
    
    # Alter existing datetime columns to be timezone-aware
    op.alter_column('schedules', 'start_time',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False)
    op.alter_column('schedules', 'end_time',
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    existing_nullable=False)
    
    # Create foreign key for recurrence_id
    op.create_foreign_key('fk_schedules_recurrence_id', 'schedules', 'schedules',
                         ['recurrence_id'], ['id'], ondelete='CASCADE')
    
    # Create indexes for recurrence
    op.create_index('ix_schedules_recurrence_id', 'schedules', ['recurrence_id'],
                    postgresql_where=sa.text('recurrence_id IS NOT NULL'))
    
    # Create schedule_reminders table
    op.create_table('schedule_reminders',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('schedule_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('minutes_before', sa.Integer(), nullable=False),
        sa.Column('method', sa.Enum('push', 'email', name='remindermethod'), nullable=False),
        sa.Column('status', sa.Enum('pending', 'sent', 'failed', 'cancelled', name='reminderstatus'), nullable=False),
        sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('failed_reason', sa.Text(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_id'], ['schedules.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_reminders_scheduled_at_status', 'schedule_reminders', 
                    ['scheduled_at', 'status'],
                    postgresql_where=sa.text("status = 'pending'"))
    op.create_index('ix_reminders_schedule_id', 'schedule_reminders', ['schedule_id'])
    
    # Create schedule_sync_queue table
    op.create_table('schedule_sync_queue',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('schedule_id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('operation', sa.Enum('UPSERT', 'DELETE', name='syncoperation'), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('pending', 'processing', 'done', 'failed', name='syncqueuestatus'), nullable=False),
        sa.Column('retry_count', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['schedule_id'], ['schedules.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sync_queue_pending', 'schedule_sync_queue',
                    ['priority', 'created_at'],
                    postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_sync_queue_pending', table_name='schedule_sync_queue')
    op.drop_index('ix_reminders_schedule_id', table_name='schedule_reminders')
    op.drop_index('ix_reminders_scheduled_at_status', table_name='schedule_reminders')
    op.drop_index('ix_schedules_recurrence_id', table_name='schedules')
    
    # Drop tables
    op.drop_table('schedule_sync_queue')
    op.drop_table('schedule_reminders')
    
    # Drop foreign key
    op.drop_constraint('fk_schedules_recurrence_id', 'schedules', type_='foreignkey')
    
    # Drop columns from schedules
    op.drop_column('schedules', 'updated_by')
    op.drop_column('schedules', 'version')
    op.drop_column('schedules', 'is_cancelled')
    op.drop_column('schedules', 'is_exception')
    op.drop_column('schedules', 'original_start_time')
    op.drop_column('schedules', 'recurrence_id')
    op.drop_column('schedules', 'recurrence_rule')
    
    # Revert datetime columns to non-timezone
    op.alter_column('schedules', 'start_time',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=False)
    op.alter_column('schedules', 'end_time',
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    existing_nullable=False)
    
    # Drop enum types
    op.execute('DROP TYPE IF EXISTS syncqueuestatus')
    op.execute('DROP TYPE IF EXISTS syncoperation')
    op.execute('DROP TYPE IF EXISTS reminderstatus')
    op.execute('DROP TYPE IF EXISTS remindermethod')
