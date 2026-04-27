"""make workspace_id NOT NULL on notes and assets

Revision ID: d234567890ab
Revises: c1234567890a
Create Date: 2026-04-27 11:00:00.000000

WARNING: Run this migration ONLY after verifying that all notes and assets
have workspace_id populated. Run scripts/verify_workspace_data.py first.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd234567890ab'
down_revision: Union[str, None] = 'c1234567890a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Verify no NULL values before making NOT NULL
    # This is a safety check - should have been verified by script already
    notes_null_count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM notes WHERE workspace_id IS NULL")
    ).scalar()
    
    if notes_null_count > 0:
        raise Exception(f"Cannot make workspace_id NOT NULL: {notes_null_count} notes still have NULL workspace_id")
    
    assets_null_count = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM assets WHERE workspace_id IS NULL")
    ).scalar()
    
    if assets_null_count > 0:
        raise Exception(f"Cannot make workspace_id NOT NULL: {assets_null_count} assets still have NULL workspace_id")
    
    # Make workspace_id NOT NULL on notes
    op.alter_column('notes', 'workspace_id', nullable=False)
    
    # Make workspace_id NOT NULL on assets
    op.alter_column('assets', 'workspace_id', nullable=False)


def downgrade() -> None:
    # Allow NULL again
    op.alter_column('assets', 'workspace_id', nullable=True)
    op.alter_column('notes', 'workspace_id', nullable=True)
