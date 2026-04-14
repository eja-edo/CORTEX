"""phase 2 ingest/search schema

Revision ID: 20260413_0003
Revises: 20260413_0002
Create Date: 2026-04-13 11:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260413_0003"
down_revision: Union[str, None] = "20260413_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    ingest_job_status_enum = postgresql.ENUM(
        "queued",
        "running",
        "success",
        "failed",
        "canceled",
        "dead",
        name="ingestjobstatus",
    )
    ingest_job_type_enum = postgresql.ENUM(
        "ingest",
        "ocr",
        "asr",
        "detect_ui",
        "summarize",
        "embed",
        "cache",
        name="ingestjobtype",
    )

    ingest_job_status_enum.create(bind, checkfirst=True)
    ingest_job_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_tags_workspace_name"),
        sa.UniqueConstraint("user_id", "name", name="uq_tags_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"], unique=False)
    op.create_index("ix_tags_workspace_id", "tags", ["workspace_id"], unique=False)

    op.create_table(
        "entity_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tag_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_tags_asset_id", "entity_tags", ["asset_id"], unique=False)
    op.create_index("ix_entity_tags_concept_id", "entity_tags", ["concept_id"], unique=False)
    op.create_index("ix_entity_tags_note_id", "entity_tags", ["note_id"], unique=False)
    op.create_index("ix_entity_tags_segment_id", "entity_tags", ["segment_id"], unique=False)
    op.create_index("ix_entity_tags_tag_id", "entity_tags", ["tag_id"], unique=False)

    op.create_table(
        "ingest_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_type", postgresql.ENUM("ingest", "ocr", "asr", "detect_ui", "summarize", "embed", "cache", name="ingestjobtype", create_type=False), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=True),
        sa.Column("parent_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", postgresql.ENUM("queued", "running", "success", "failed", "canceled", "dead", name="ingestjobstatus", create_type=False), nullable=False, server_default=sa.text("'queued'")),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("progress", sa.Numeric(5, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_job_id"], ["ingest_jobs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_ingest_jobs_idempotency_key"),
    )
    op.create_index("ix_ingest_jobs_asset_job_stage", "ingest_jobs", ["asset_id", "job_type", "stage"], unique=False)
    op.create_index("ix_ingest_jobs_asset_id", "ingest_jobs", ["asset_id"], unique=False)
    op.create_index("ix_ingest_jobs_parent_job_id", "ingest_jobs", ["parent_job_id"], unique=False)
    op.create_index("ix_ingest_jobs_status_created_at", "ingest_jobs", ["status", "created_at"], unique=False)
    op.create_index("ix_ingest_jobs_user_created", "ingest_jobs", ["user_id", "created_at"], unique=False)
    op.create_index("ix_ingest_jobs_user_id", "ingest_jobs", ["user_id"], unique=False)

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notifications_user_read_created", "notifications", ["user_id", "read_at", "created_at"], unique=False)
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"], unique=False)

    op.create_table(
        "note_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "model", name="uq_note_embeddings_note_model"),
    )
    op.create_index("ix_note_embeddings_note_current", "note_embeddings", ["note_id", "is_current"], unique=False)
    op.create_index("ix_note_embeddings_note_id", "note_embeddings", ["note_id"], unique=False)

    op.create_table(
        "segment_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("segment_id", "model", name="uq_segment_embeddings_segment_model"),
    )
    op.create_index("ix_segment_embeddings_segment_current", "segment_embeddings", ["segment_id", "is_current"], unique=False)
    op.create_index("ix_segment_embeddings_segment_id", "segment_embeddings", ["segment_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_segment_embeddings_segment_id", table_name="segment_embeddings")
    op.drop_index("ix_segment_embeddings_segment_current", table_name="segment_embeddings")
    op.drop_table("segment_embeddings")

    op.drop_index("ix_note_embeddings_note_id", table_name="note_embeddings")
    op.drop_index("ix_note_embeddings_note_current", table_name="note_embeddings")
    op.drop_table("note_embeddings")

    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_notifications_user_read_created", table_name="notifications")
    op.drop_table("notifications")

    op.drop_index("ix_ingest_jobs_user_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_user_created", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_status_created_at", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_parent_job_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_asset_id", table_name="ingest_jobs")
    op.drop_index("ix_ingest_jobs_asset_job_stage", table_name="ingest_jobs")
    op.drop_table("ingest_jobs")

    op.drop_index("ix_entity_tags_tag_id", table_name="entity_tags")
    op.drop_index("ix_entity_tags_segment_id", table_name="entity_tags")
    op.drop_index("ix_entity_tags_note_id", table_name="entity_tags")
    op.drop_index("ix_entity_tags_concept_id", table_name="entity_tags")
    op.drop_index("ix_entity_tags_asset_id", table_name="entity_tags")
    op.drop_table("entity_tags")

    op.drop_index("ix_tags_workspace_id", table_name="tags")
    op.drop_index("ix_tags_user_id", table_name="tags")
    op.drop_table("tags")

    ingest_job_type_enum = postgresql.ENUM(
        "ingest",
        "ocr",
        "asr",
        "detect_ui",
        "summarize",
        "embed",
        "cache",
        name="ingestjobtype",
    )
    ingest_job_status_enum = postgresql.ENUM(
        "queued",
        "running",
        "success",
        "failed",
        "canceled",
        "dead",
        name="ingestjobstatus",
    )

    ingest_job_type_enum.drop(bind, checkfirst=True)
    ingest_job_status_enum.drop(bind, checkfirst=True)
