"""add content and actions JSONB columns to notifications

Revision ID: 60825a32d089
Revises: k6789012345g
Create Date: 2026-07-02 11:52:33.494055

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '60825a32d089'
down_revision: Union[str, None] = 'k6789012345g'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('notifications', sa.Column('content', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column('notifications', sa.Column('actions', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False))


def downgrade() -> None:
    op.drop_column('notifications', 'content')
    op.drop_column('notifications', 'actions')
