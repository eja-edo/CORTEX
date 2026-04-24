"""drop_schedule_sync_queue_table

Revision ID: e8916bf7593a
Revises: b9536f24e86d
Create Date: 2026-04-25 00:48:45.792754

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8916bf7593a'
down_revision: Union[str, None] = 'b9536f24e86d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
