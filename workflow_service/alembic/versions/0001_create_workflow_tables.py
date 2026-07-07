"""create workflow tables

Revision ID: 0001
Revises:
Create Date: 2026-06-25 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS workflow")

    op.create_table(
        "workflow_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("DRAFT", "ACTIVE", "PAUSED", "ARCHIVED", name="workflowstatus"),
            nullable=False,
            server_default="DRAFT",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "trigger_type",
            sa.Enum(
                "INTERNAL_EVENT",
                "WEBHOOK",
                "SCHEDULE",
                "MANUAL",
                name="triggertype",
            ),
            nullable=False,
        ),
        sa.Column("trigger_config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("definition", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("webhook_secret", sa.String(255), nullable=True),
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
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        schema="workflow",
    )

    op.create_table(
        "workflow_trigger_webhooks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_definitions.id"),
            nullable=False,
        ),
        sa.Column("webhook_path", sa.String(255), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        schema="workflow",
    )

    op.create_table(
        "workflow_instances",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workflow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_definitions.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "WAITING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                name="executionstatus",
            ),
            nullable=False,
            server_default="PENDING",
        ),
        sa.Column("temporal_workflow_id", sa.String(255), nullable=True),
        sa.Column("temporal_run_id", sa.String(255), nullable=True),
        sa.Column("trigger_data", sa.JSON(), nullable=True),
        sa.Column("output", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="workflow",
    )

    op.create_table(
        "workflow_step_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "instance_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workflow.workflow_instances.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("node_id", sa.String(255), nullable=False),
        sa.Column("node_type", sa.String(100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "WAITING",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                "TIMED_OUT",
                name="executionstatus",
            ),
            nullable=False,
        ),
        sa.Column("input_data", sa.JSON(), nullable=True),
        sa.Column("output_data", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="workflow",
    )


def downgrade() -> None:
    op.drop_table("workflow_step_executions", schema="workflow")
    op.drop_table("workflow_instances", schema="workflow")
    op.drop_table("workflow_trigger_webhooks", schema="workflow")
    op.drop_table("workflow_definitions", schema="workflow")

    op.execute("DROP TYPE IF EXISTS executionstatus")
    op.execute("DROP TYPE IF EXISTS workflowstatus")
    op.execute("DROP TYPE IF EXISTS triggertype")
