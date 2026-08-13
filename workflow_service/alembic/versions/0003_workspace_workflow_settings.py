"""workspace_workflow_settings table (Milestone 4.0 M1)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspace_workflow_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_definitions.id"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("config_overrides", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "forked_workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_definitions.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("workspace_id", "workflow_id", name="uq_workspace_workflow"),
        schema="workflow",
    )


def downgrade() -> None:
    op.drop_table("workspace_workflow_settings", schema="workflow")
