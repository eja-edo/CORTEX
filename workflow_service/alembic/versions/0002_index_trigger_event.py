"""index trigger_config event for SQL-side trigger matching (Milestone 4.0 M2)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_workflow_definitions_trigger_event
        ON workflow.workflow_definitions ((trigger_config->>'event'))
        WHERE status = 'ACTIVE' AND trigger_type = 'INTERNAL_EVENT' AND is_deleted = false
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX workflow.ix_workflow_definitions_trigger_event")
