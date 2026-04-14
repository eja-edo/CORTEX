"""knowledge phase 1 schema

Revision ID: 20260413_0002
Revises: 20260413_0001
Create Date: 2026-04-13 10:15:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260413_0002"
down_revision: Union[str, None] = "20260413_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    asset_type_enum = postgresql.ENUM("uploaded_video", "screen_recording", "live_session", name="assettype")
    asset_status_enum = postgresql.ENUM("pending", "processing", "ready", "failed", "archived", name="assetstatus")
    segment_source_enum = postgresql.ENUM("ocr", "asr", "ui_detection", "user_highlight", "ai_detection", name="segmentsource")
    link_type_enum = postgresql.ENUM("reference", "highlight", "derived", name="linktype")
    derivative_type_enum = postgresql.ENUM("thumbnail", "waveform", "transcript", "keyframes", "summary_clip", name="derivativetype")

    asset_type_enum.create(bind, checkfirst=True)
    asset_status_enum.create(bind, checkfirst=True)
    segment_source_enum.create(bind, checkfirst=True)
    link_type_enum.create(bind, checkfirst=True)
    derivative_type_enum.create(bind, checkfirst=True)

    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("owner_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan", sa.String(length=32), nullable=False, server_default=sa.text("'free'")),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_owner_user_id", "workspaces", ["owner_user_id"], unique=False)

    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default=sa.text("'member'")),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
    )

    op.create_table(
        "workspace_quotas",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_storage_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("10737418240")),
        sa.Column("used_storage_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default=sa.text("3")),
        sa.Column("max_assets", sa.Integer(), nullable=False, server_default=sa.text("100")),
        sa.Column("ai_tokens_monthly_limit", sa.BigInteger(), nullable=False, server_default=sa.text("1000000")),
        sa.Column("ai_tokens_used_month", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("quota_reset_at", sa.DateTime(), nullable=False, server_default=sa.text("date_trunc('month', now()) + interval '1 month'")),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("workspace_id"),
    )

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type", postgresql.ENUM("uploaded_video", "screen_recording", "live_session", name="assettype", create_type=False), nullable=False),
        sa.Column("status", postgresql.ENUM("pending", "processing", "ready", "failed", "archived", name="assetstatus", create_type=False), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_upload_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_object_key", sa.String(length=1024), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("frame_rate", sa.Numeric(8, 3), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column("captured_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("failed_reason", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_upload_id"], ["uploads.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_checksum_sha256", "assets", ["checksum_sha256"], unique=False)
    op.create_index("ix_assets_source_upload_id", "assets", ["source_upload_id"], unique=False)
    op.create_index("ix_assets_user_created", "assets", ["user_id", "created_at"], unique=False)
    op.create_index("ix_assets_user_id", "assets", ["user_id"], unique=False)
    op.create_index("ix_assets_user_status", "assets", ["user_id", "status"], unique=False)
    op.create_index("ix_assets_workspace_created", "assets", ["workspace_id", "created_at"], unique=False)
    op.create_index("ix_assets_workspace_id", "assets", ["workspace_id"], unique=False)

    op.create_table(
        "asset_derivatives",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("derivative_type", postgresql.ENUM("thumbnail", "waveform", "transcript", "keyframes", "summary_clip", name="derivativetype", create_type=False), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("format", sa.String(length=32), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "derivative_type", name="uq_asset_derivatives_asset_type"),
    )
    op.create_index("ix_asset_derivatives_asset_id", "asset_derivatives", ["asset_id"], unique=False)

    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("source", postgresql.ENUM("ocr", "asr", "ui_detection", "user_highlight", "ai_detection", name="segmentsource", create_type=False), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("keyframe_url", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id", "external_id", name="uq_segments_asset_external_id"),
    )
    op.create_index("ix_segments_asset_id", "segments", ["asset_id"], unique=False)
    op.create_index("ix_segments_asset_start", "segments", ["asset_id", "start_ms"], unique=False)
    op.create_index("ix_segments_user_created", "segments", ["user_id", "created_at"], unique=False)
    op.create_index("ix_segments_user_id", "segments", ["user_id"], unique=False)

    op.create_table(
        "segment_contents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("segment_id", "content_type", "language", name="uq_segment_contents_triplet"),
    )
    op.create_index("ix_segment_contents_segment_id", "segment_contents", ["segment_id"], unique=False)
    op.create_index("ix_segment_contents_segment_type", "segment_contents", ["segment_id", "content_type"], unique=False)

    op.create_table(
        "note_segment_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_start_ms", sa.BigInteger(), nullable=False),
        sa.Column("linked_end_ms", sa.BigInteger(), nullable=False),
        sa.Column("link_type", postgresql.ENUM("reference", "highlight", "derived", name="linktype", create_type=False), nullable=False, server_default=sa.text("'reference'")),
        sa.Column("weight", sa.Numeric(5, 4), nullable=False, server_default=sa.text("1.0")),
        sa.Column("anchor_text", sa.Text(), nullable=True),
        sa.Column("start_offset", sa.Integer(), nullable=True),
        sa.Column("end_offset", sa.Integer(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["linked_asset_id"], ["assets.id"]),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "segment_id", "link_type", name="uq_note_segment_links_unique"),
    )
    op.create_index("ix_note_segment_links_asset_time", "note_segment_links", ["linked_asset_id", "linked_start_ms"], unique=False)
    op.create_index("ix_note_segment_links_linked_asset_id", "note_segment_links", ["linked_asset_id"], unique=False)
    op.create_index("ix_note_segment_links_note_id", "note_segment_links", ["note_id"], unique=False)
    op.create_index("ix_note_segment_links_note_type", "note_segment_links", ["note_id", "link_type"], unique=False)
    op.create_index("ix_note_segment_links_segment_id", "note_segment_links", ["segment_id"], unique=False)
    op.create_index("ix_note_segment_links_segment_type", "note_segment_links", ["segment_id", "link_type"], unique=False)
    op.create_index("ix_note_segment_links_user_id", "note_segment_links", ["user_id"], unique=False)

    op.create_table(
        "bookmarks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "asset_id", "segment_id", name="uq_bookmarks_user_asset_segment"),
    )
    op.create_index("ix_bookmarks_asset_id", "bookmarks", ["asset_id"], unique=False)
    op.create_index("ix_bookmarks_segment_id", "bookmarks", ["segment_id"], unique=False)
    op.create_index("ix_bookmarks_user_asset_created", "bookmarks", ["user_id", "asset_id", "created_at"], unique=False)
    op.create_index("ix_bookmarks_user_id", "bookmarks", ["user_id"], unique=False)

    op.create_table(
        "asset_timeline_cache",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_dirty", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("timeline", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("asset_id"),
    )


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_table("asset_timeline_cache")

    op.drop_index("ix_bookmarks_user_id", table_name="bookmarks")
    op.drop_index("ix_bookmarks_user_asset_created", table_name="bookmarks")
    op.drop_index("ix_bookmarks_segment_id", table_name="bookmarks")
    op.drop_index("ix_bookmarks_asset_id", table_name="bookmarks")
    op.drop_table("bookmarks")

    op.drop_index("ix_note_segment_links_user_id", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_segment_type", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_segment_id", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_note_type", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_note_id", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_linked_asset_id", table_name="note_segment_links")
    op.drop_index("ix_note_segment_links_asset_time", table_name="note_segment_links")
    op.drop_table("note_segment_links")

    op.drop_index("ix_segment_contents_segment_type", table_name="segment_contents")
    op.drop_index("ix_segment_contents_segment_id", table_name="segment_contents")
    op.drop_table("segment_contents")

    op.drop_index("ix_segments_user_id", table_name="segments")
    op.drop_index("ix_segments_user_created", table_name="segments")
    op.drop_index("ix_segments_asset_start", table_name="segments")
    op.drop_index("ix_segments_asset_id", table_name="segments")
    op.drop_table("segments")

    op.drop_index("ix_asset_derivatives_asset_id", table_name="asset_derivatives")
    op.drop_table("asset_derivatives")

    op.drop_index("ix_assets_workspace_id", table_name="assets")
    op.drop_index("ix_assets_workspace_created", table_name="assets")
    op.drop_index("ix_assets_user_status", table_name="assets")
    op.drop_index("ix_assets_user_id", table_name="assets")
    op.drop_index("ix_assets_user_created", table_name="assets")
    op.drop_index("ix_assets_source_upload_id", table_name="assets")
    op.drop_index("ix_assets_checksum_sha256", table_name="assets")
    op.drop_table("assets")

    op.drop_table("workspace_quotas")
    op.drop_table("workspace_members")
    op.drop_index("ix_workspaces_owner_user_id", table_name="workspaces")
    op.drop_table("workspaces")

    derivative_type_enum = postgresql.ENUM("thumbnail", "waveform", "transcript", "keyframes", "summary_clip", name="derivativetype")
    link_type_enum = postgresql.ENUM("reference", "highlight", "derived", name="linktype")
    segment_source_enum = postgresql.ENUM("ocr", "asr", "ui_detection", "user_highlight", "ai_detection", name="segmentsource")
    asset_status_enum = postgresql.ENUM("pending", "processing", "ready", "failed", "archived", name="assetstatus")
    asset_type_enum = postgresql.ENUM("uploaded_video", "screen_recording", "live_session", name="assettype")

    derivative_type_enum.drop(bind, checkfirst=True)
    link_type_enum.drop(bind, checkfirst=True)
    segment_source_enum.drop(bind, checkfirst=True)
    asset_status_enum.drop(bind, checkfirst=True)
    asset_type_enum.drop(bind, checkfirst=True)
