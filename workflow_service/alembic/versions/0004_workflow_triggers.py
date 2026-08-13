"""workflow_triggers table for multi-trigger workflows

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ENUM, UUID

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_triggers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", UUID(as_uuid=True), sa.ForeignKey("workflow.workflow_definitions.id"), nullable=False, index=True),
        sa.Column(
            "trigger_type",
            ENUM("INTERNAL_EVENT", "WEBHOOK", "SCHEDULE", "MANUAL", name="triggertype", create_type=False),
            nullable=False,
        ),
        sa.Column("trigger_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema="workflow",
    )

    op.add_column(
        "workflow_trigger_webhooks",
        sa.Column(
            "trigger_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_triggers.id"),
            nullable=True,
        ),
        schema="workflow",
    )


def downgrade() -> None:
    op.drop_column("workflow_trigger_webhooks", "trigger_id", schema="workflow")
    op.drop_table("workflow_triggers", schema="workflow")
