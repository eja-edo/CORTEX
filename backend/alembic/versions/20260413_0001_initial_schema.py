"""initial schema

Revision ID: 20260413_0001
Revises:
Create Date: 2026-04-13 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "20260413_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    schedule_type_enum = postgresql.ENUM("CLASS", "DEADLINE", "EXAM", "PERSONAL", name="scheduletype")
    calendar_provider_enum = postgresql.ENUM("GOOGLE", name="calendarprovider")
    sync_source_enum = postgresql.ENUM("INTERNAL", "PROVIDER", name="syncsource")
    upload_status_enum = postgresql.ENUM("initiated", "uploading", "completed", "failed", name="uploadstatus")

    schedule_type_enum.create(bind, checkfirst=True)
    calendar_provider_enum.create(bind, checkfirst=True)
    sync_source_enum.create(bind, checkfirst=True)
    upload_status_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False, server_default=sa.text("'markdown'")),
        sa.Column("position", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("jsonb_build_object('x', 0, 'y', 0)")),
        sa.Column("size", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("jsonb_build_object('width', 200, 'height', 200)")),
        sa.Column("style", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("jsonb_build_object('color', 'yellow')")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_notes_user_id", "notes", ["user_id"], unique=False)
    op.create_index("ix_notes_user_id_updated_at", "notes", ["user_id", "updated_at"], unique=False)

    op.create_table(
        "authorization_codes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.String(length=255), nullable=False),
        sa.Column("redirect_uri", sa.String(length=1000), nullable=False),
        sa.Column("code_challenge", sa.String(length=255), nullable=False),
        sa.Column("code_challenge_method", sa.String(length=10), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_authorization_codes_code_hash", "authorization_codes", ["code_hash"], unique=True)
    op.create_index("ix_authorization_codes_user_id", "authorization_codes", ["user_id"], unique=False)

    op.create_table(
        "calendar_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM("GOOGLE", name="calendarprovider", create_type=False), nullable=False),
        sa.Column("provider_calendar_id", sa.String(length=255), nullable=False, server_default=sa.text("'primary'")),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("granted_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("sync_token", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_error", sa.Text(), nullable=True),
        sa.Column("channel_id", sa.String(length=64), nullable=True),
        sa.Column("channel_resource_id", sa.String(length=255), nullable=True),
        sa.Column("channel_expiration", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", "provider_calendar_id", name="uq_calendar_connections_user_provider_calendar"),
    )
    op.create_index("ix_calendar_connections_provider_last_synced_at", "calendar_connections", ["provider", "last_synced_at"], unique=False)
    op.create_index("ix_calendar_connections_user_id", "calendar_connections", ["user_id"], unique=False)

    op.create_table(
        "oauth_states",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM("GOOGLE", name="calendarprovider", create_type=False), nullable=False),
        sa.Column("state_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_states_provider_expires_at", "oauth_states", ["provider", "expires_at"], unique=False)
    op.create_index("ix_oauth_states_state_hash", "oauth_states", ["state_hash"], unique=True)
    op.create_index("ix_oauth_states_user_id", "oauth_states", ["user_id"], unique=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("jti", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_refresh_tokens_jti", "refresh_tokens", ["jti"], unique=True)
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"], unique=False)

    op.create_table(
        "schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("type", postgresql.ENUM("CLASS", "DEADLINE", "EXAM", "PERSONAL", name="scheduletype", create_type=False), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("is_completed", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_schedules_user_id", "schedules", ["user_id"], unique=False)

    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", postgresql.ENUM("initiated", "uploading", "completed", "failed", name="uploadstatus", create_type=False), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("upload_id", sa.String(length=255), nullable=False),
        sa.Column("total_parts", sa.Integer(), nullable=False),
        sa.Column("total_size", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_uploads_object_key", "uploads", ["object_key"], unique=True)
    op.create_index("ix_uploads_upload_id", "uploads", ["upload_id"], unique=True)
    op.create_index("ix_uploads_user_id", "uploads", ["user_id"], unique=False)
    op.create_index("ix_uploads_user_status_created_at", "uploads", ["user_id", "status", "created_at"], unique=False)

    op.create_table(
        "schedule_external_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", postgresql.ENUM("GOOGLE", name="calendarprovider", create_type=False), nullable=False),
        sa.Column("provider_calendar_id", sa.String(length=255), nullable=False, server_default=sa.text("'primary'")),
        sa.Column("provider_event_id", sa.String(length=1024), nullable=False),
        sa.Column("provider_etag", sa.String(length=255), nullable=True),
        sa.Column("provider_updated_at", sa.DateTime(), nullable=True),
        sa.Column("last_sync_source", postgresql.ENUM("INTERNAL", "PROVIDER", name="syncsource", create_type=False), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("is_deleted_remote", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedules.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_calendar_id", "provider_event_id", name="uq_schedule_external_maps_provider_event"),
        sa.UniqueConstraint("schedule_id", "provider", name="uq_schedule_external_maps_schedule_provider"),
    )
    op.create_index("ix_schedule_external_maps_provider_event_id", "schedule_external_maps", ["provider_event_id"], unique=False)
    op.create_index("ix_schedule_external_maps_schedule_id", "schedule_external_maps", ["schedule_id"], unique=False)
    op.create_index("ix_schedule_external_maps_user_id", "schedule_external_maps", ["user_id"], unique=False)
    op.create_index("ix_schedule_external_maps_user_provider", "schedule_external_maps", ["user_id", "provider"], unique=False)

    op.create_table(
        "upload_parts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("upload_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("part_number", sa.Integer(), nullable=False),
        sa.Column("etag", sa.String(length=255), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["upload_record_id"], ["uploads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("upload_record_id", "part_number", name="uq_upload_parts_upload_part_number"),
    )
    op.create_index("ix_upload_parts_upload_part_number", "upload_parts", ["upload_record_id", "part_number"], unique=False)
    op.create_index("ix_upload_parts_upload_record_id", "upload_parts", ["upload_record_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_index("ix_upload_parts_upload_record_id", table_name="upload_parts")
    op.drop_index("ix_upload_parts_upload_part_number", table_name="upload_parts")
    op.drop_table("upload_parts")

    op.drop_index("ix_schedule_external_maps_user_provider", table_name="schedule_external_maps")
    op.drop_index("ix_schedule_external_maps_user_id", table_name="schedule_external_maps")
    op.drop_index("ix_schedule_external_maps_schedule_id", table_name="schedule_external_maps")
    op.drop_index("ix_schedule_external_maps_provider_event_id", table_name="schedule_external_maps")
    op.drop_table("schedule_external_maps")

    op.drop_index("ix_uploads_user_status_created_at", table_name="uploads")
    op.drop_index("ix_uploads_user_id", table_name="uploads")
    op.drop_index("ix_uploads_upload_id", table_name="uploads")
    op.drop_index("ix_uploads_object_key", table_name="uploads")
    op.drop_table("uploads")

    op.drop_index("ix_schedules_user_id", table_name="schedules")
    op.drop_table("schedules")

    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_jti", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.drop_index("ix_oauth_states_user_id", table_name="oauth_states")
    op.drop_index("ix_oauth_states_state_hash", table_name="oauth_states")
    op.drop_index("ix_oauth_states_provider_expires_at", table_name="oauth_states")
    op.drop_table("oauth_states")

    op.drop_index("ix_calendar_connections_user_id", table_name="calendar_connections")
    op.drop_index("ix_calendar_connections_provider_last_synced_at", table_name="calendar_connections")
    op.drop_table("calendar_connections")

    op.drop_index("ix_authorization_codes_user_id", table_name="authorization_codes")
    op.drop_index("ix_authorization_codes_code_hash", table_name="authorization_codes")
    op.drop_table("authorization_codes")

    op.drop_index("ix_notes_user_id_updated_at", table_name="notes")
    op.drop_index("ix_notes_user_id", table_name="notes")
    op.drop_table("notes")

    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

    upload_status_enum = postgresql.ENUM("initiated", "uploading", "completed", "failed", name="uploadstatus")
    sync_source_enum = postgresql.ENUM("INTERNAL", "PROVIDER", name="syncsource")
    calendar_provider_enum = postgresql.ENUM("GOOGLE", name="calendarprovider")
    schedule_type_enum = postgresql.ENUM("CLASS", "DEADLINE", "EXAM", "PERSONAL", name="scheduletype")

    upload_status_enum.drop(bind, checkfirst=True)
    sync_source_enum.drop(bind, checkfirst=True)
    calendar_provider_enum.drop(bind, checkfirst=True)
    schedule_type_enum.drop(bind, checkfirst=True)
