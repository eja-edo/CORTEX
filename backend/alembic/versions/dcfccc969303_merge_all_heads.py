"""merge all heads

Revision ID: dcfccc969303
Revises: 006, 6ff91525347b, 60825a32d089
Create Date: 2026-07-07 09:37:32.358163

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcfccc969303'
down_revision: Union[str, None] = ('006', '6ff91525347b', '60825a32d089')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
