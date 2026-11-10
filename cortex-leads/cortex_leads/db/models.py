"""Full v0 schema (PLAN §3.3). Every table except tenant/connector/api_key is tenant-scoped + RLS
(RLS itself is applied in the migration). Other WPs must not edit this file."""
import re
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from cortex_leads.auth.roles import ApiRole
from cortex_leads.core.ids import uuid7


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={"ck": "ck_%(table_name)s_%(constraint_name)s"})
    type_annotation_map = {
        UUID: PGUUID(as_uuid=True),
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
        list[dict[str, Any]]: JSONB,
        list[str]: ARRAY(Text),
    }


def _enum(col: str, *values: str) -> CheckConstraint:
    vals = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{col} in ({vals})", name=col)


def pk() -> Mapped[UUID]:
    return mapped_column(primary_key=True, default=uuid7)


def tid() -> Mapped[UUID]:
    return mapped_column(nullable=False)


def created() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


# Tables WITHOUT row level security: looked up before the tenant is known.
NO_RLS = {"tenant", "connector", "api_key", "login_throttle", "platform_admin"}


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Ho_Chi_Minh")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    ai_name: Mapped[str | None] = mapped_column(Text)  # the name the AI introduces itself by (WP39); empty = the business's own name
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("status", "active", "paused"),)


class Sandbox(Base):
    __tablename__ = "sandbox"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    name: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, server_default="customer_care")
    title: Mapped[str | None] = mapped_column(Text)  # what the owner calls it; `name` stays the internal key
    profile_ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    isolation: Mapped[str] = mapped_column(Text, server_default="logical")
    budget: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    send_mode: Mapped[str] = mapped_column(Text, server_default="manual")
    domain_pack: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    business_hours: Mapped[dict[str, Any]] = mapped_column(
        server_default=sql_text('\'{"start":"08:00","end":"21:00"}\'::jsonb'))
    tools_off: Mapped[list[str]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))  # tools the owner switched off here
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("status", "active", "paused"),
        _enum("send_mode", "auto", "manual"),
        Index("ix_sandbox_tenant", "tenant_id", "id"),
    )

    @validates("purpose")
    def _purpose(self, _key: str, v: str) -> str:  # no CHECK: purposes are domain-defined (A6)
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(f"sandbox purpose must be a lowercase slug, got {v!r}")
        return v


class Connector(Base):
    __tablename__ = "connector"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    channel_kind: Mapped[str] = mapped_column(Text)
    trust: Mapped[str] = mapped_column(Text, server_default="custom")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)  # Fernet token
    outbound: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    contract_test_passed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("trust", "official", "partner", "custom"),
        _enum("status", "active", "disabled"),
    )


class ApiKey(Base):
    __tablename__ = "api_key"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    key_hash: Mapped[str] = mapped_column(Text, unique=True)  # sha256 hex
    role: Mapped[str] = mapped_column(Text)
    staff_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    revoked_at: Mapped[datetime | None]
    __table_args__ = (_enum("role", *ApiRole),)


class Contact(Base):
    __tablename__ = "contact"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    external_id: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)
    opted_out: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    decision_maker: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("tenant_id", "connector_id", "external_id"),)


class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    external_id: Mapped[str] = mapped_column(Text)
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id"))
    channel_kind: Mapped[str] = mapped_column(Text)
    intent: Mapped[str | None] = mapped_column(Text)
    owner_staff_ref: Mapped[str | None] = mapped_column(Text)
    last_customer_at: Mapped[datetime | None]
    last_customer_msg_id: Mapped[str | None] = mapped_column(Text)
    last_staff_at: Mapped[datetime | None]
    next_check_at: Mapped[datetime | None]
    reply_check_at: Mapped[datetime | None]  # WP16: customer finished a turn nobody answered
    reply_waits: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    promised_date: Mapped[date | None] = mapped_column(Date)
    offchannel_contact: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    touches: Mapped[int] = mapped_column(Integer, server_default="0")
    state: Mapped[str] = mapped_column(Text, server_default="open")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_id", "external_id"),
        _enum("state", "open", "booked", "won", "lost", "opted_out"),
        Index(
            "ix_conversation_next_check",
            "tenant_id",
            "next_check_at",
            postgresql_where=sql_text("next_check_at is not null"),
        ),
        Index("ix_conversation_reply_check", "tenant_id", "reply_check_at",
              postgresql_where=sql_text("reply_check_at is not null")),
    )


class Message(Base):
    __tablename__ = "message"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    external_id: Mapped[str] = mapped_column(Text)
    sender_role: Mapped[str] = mapped_column(Text)
    staff_ref: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime]
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_id", "external_id"),
        _enum("sender_role", "customer", "staff", "bot"),
        Index("ix_message_conv", "tenant_id", "conversation_id", "occurred_at"),
    )


class IngestEvent(Base):
    __tablename__ = "ingest_event"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    external_id: Mapped[str] = mapped_column(Text)
    type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_id", "external_id"),
        _enum("status", "accepted", "duplicate", "rejected", "processed"),
    )


class CatalogItem(Base):
    __tablename__ = "catalog_item"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(Text)
    price: Mapped[float | None] = mapped_column(Numeric)
    unit: Mapped[str | None] = mapped_column(Text)
    attrs: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    valid_until: Mapped[datetime | None]
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    __table_args__ = (UniqueConstraint("tenant_id", "code", "version"),)


class SkillVersion(Base):
    __tablename__ = "skill_version"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    name: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, server_default="draft")
    manifest: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    body: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    form_spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)  # a form skill: the fields as filled, to edit from
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # soft delete: hidden, restorable
    deleted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # last in-place edit: trial runs count from here
    __table_args__ = (
        UniqueConstraint("tenant_id", "sandbox_id", "name", "version"),
        _enum("status", "draft", "shadow", "live", "retired"),
        Index(
            "uq_skill_live",
            "tenant_id",
            "sandbox_id",
            "name",
            unique=True,
            postgresql_where=sql_text("status = 'live'"),
        ),
    )


class FollowupJob(Base):
    __tablename__ = "followup_job"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    skill_name: Mapped[str] = mapped_column(Text)
    skill_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    not_before: Mapped[datetime] = created()
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "sandbox_id", "skill_name", "dedupe_key"),
        _enum("status", "pending", "running", "done", "skipped", "failed"),
        Index("ix_followup_job_pick", "tenant_id", "status", "not_before"),
    )


class TriggerRun(Base):
    """No free-text column on purpose: this is what the supervisor may see (DESIGN §5.6)."""

    __tablename__ = "trigger_run"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("followup_job.id"))
    skill_name: Mapped[str] = mapped_column(Text)
    skill_version: Mapped[int] = mapped_column(Integer)
    profile: Mapped[str] = mapped_column(Text)
    profile_version: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    act: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    blocked_codes: Mapped[list[str]] = mapped_column(server_default=sql_text("'{}'::text[]"))
    tokens_in: Mapped[int] = mapped_column(BigInteger, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, server_default="0")
    model: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None]
    staff_outcome: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        _enum("status", "ok", "none", "blocked", "error", "budget_denied", "paused"),
        _enum("act", "none", "draft"),
        _enum("staff_outcome", "sent", "edited", "self", "skipped"),
        Index("ix_trigger_run_started", "tenant_id", "started_at"),
    )


class Draft(Base):
    __tablename__ = "draft"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("trigger_run.id"))
    status: Mapped[str] = mapped_column(Text, server_default="proposed")
    route: Mapped[str] = mapped_column(Text, server_default="channel")  # offchannel: never in the outbox
    needs_human: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))  # WP16 handoff
    text: Mapped[str] = mapped_column(Text)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(server_default=sql_text("'[]'::jsonb"))
    reason_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    decided_at: Mapped[datetime | None]
    staff_ref: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        _enum("status", "proposed", "approved", "sent", "edited", "self", "skipped", "expired",
              "blocked", "failed", "shadow"),  # shadow: a skill on trial wrote it; nobody is shown it, nothing is sent
        _enum("route", "channel", "offchannel"),
        Index("ix_draft_conv", "tenant_id", "conversation_id", "status"),
    )


class StaffAction(Base):
    __tablename__ = "staff_action"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("draft.id"))
    action: Mapped[str] = mapped_column(Text)
    edited_text: Mapped[str | None] = mapped_column(Text)
    staff_ref: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = created()
    __table_args__ = (_enum("action", "approved", "sent", "edited", "self", "skipped"),)


class DecisionLog(Base):
    __tablename__ = "decision_log"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    run_id: Mapped[UUID | None]
    conversation_id: Mapped[UUID | None]
    decision: Mapped[str] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))  # no customer text
    at: Mapped[datetime] = created()
    __table_args__ = (Index("ix_decision_log_at", "tenant_id", "at"),)


class ActionLog(Base):
    __tablename__ = "action_log"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    action_id: Mapped[UUID]
    actor: Mapped[str] = mapped_column(Text)
    tool: Mapped[str] = mapped_column(Text)
    args_masked: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text)
    at: Mapped[datetime] = created()
    __table_args__ = (Index("ix_action_log_at", "tenant_id", "at"),)


class ContactFact(Base):
    """Facts about a contact; `value` is free text/JSON, so the supervisor may not read it."""

    __tablename__ = "contact_fact"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id"))
    conversation_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation.id"))
    kind: Mapped[str] = mapped_column(Text)
    value: Mapped[Any] = mapped_column(JSONB)
    evidence_msg_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), server_default=sql_text("'{}'::uuid[]"))
    source: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="candidate")
    superseded_by: Mapped[UUID | None] = mapped_column(ForeignKey("contact_fact.id"))
    created_at: Mapped[datetime] = created()
    updated_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("status", "candidate", "active", "superseded", "fulfilled", "cancelled", "done",
              "rejected"),
        Index("ix_contact_fact_lookup", "tenant_id", "contact_id", "kind", "status"),
    )


class Deal(Base):
    __tablename__ = "deal"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    external_id: Mapped[str] = mapped_column(Text)
    contact_id: Mapped[UUID | None] = mapped_column(ForeignKey("contact.id"))
    conversation_id: Mapped[UUID | None] = mapped_column(ForeignKey("conversation.id"))
    status: Mapped[str] = mapped_column(Text)
    value: Mapped[float | None] = mapped_column(Numeric)
    currency: Mapped[str] = mapped_column(Text, server_default="VND")
    occurred_at: Mapped[datetime]
    linked: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        UniqueConstraint("tenant_id", "connector_id", "external_id"),
        _enum("status", "booked", "won", "lost", "cancelled"),
    )


class Outbox(Base):
    __tablename__ = "outbox"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    action_id: Mapped[UUID] = mapped_column(unique=True)
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    connector_id: Mapped[str] = mapped_column(ForeignKey("connector.id"))
    draft_id: Mapped[UUID | None] = mapped_column(ForeignKey("draft.id"))
    kind: Mapped[str] = mapped_column(Text, server_default="message")  # message | add_tag | add_note (WP24)
    actor: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    disclosure: Mapped[str | None] = mapped_column(Text)
    window: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    source: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    not_before: Mapped[datetime | None]
    external_message_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    sent_at: Mapped[datetime | None]
    __table_args__ = (
        _enum("status", "queued", "sending", "sent", "refused", "error", "cancelled"),
        _enum("kind", "message", "add_tag", "add_note"),
        Index("ix_outbox_pick", "tenant_id", "status", "not_before"),
    )


class NotifyTarget(Base):
    """Where staff pushes go (WP17). `address` is a Telegram chat id; the bot token is global config."""

    __tablename__ = "notify_target"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    kind: Mapped[str] = mapped_column(Text, server_default="telegram")
    address: Mapped[str] = mapped_column(Text)  # telegram: chat id; mezon: https webhook URL (WP31)
    label: Mapped[str | None] = mapped_column(Text)
    # A target bound to a sandbox gets only what that sandbox produces, and wins over the unbound ones for it (WP35, R120); unbound = the
    # business's general channel.
    sandbox_id: Mapped[UUID | None] = mapped_column(ForeignKey("sandbox.id"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("kind", "telegram", "mezon"), UniqueConstraint("tenant_id", "kind", "address"))


class Notification(Base):
    """A push owed to staff. No customer text: `kind` + `ref_id` only (the message is built from counts)."""

    __tablename__ = "notification"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    kind: Mapped[str] = mapped_column(Text)
    ref_id: Mapped[UUID]
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    not_before: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    sent_at: Mapped[datetime | None]
    __table_args__ = (
        _enum("kind", "handoff", "booking", "task", "digest", "proposal", "lesson", "grading"),
        _enum("status", "queued", "sent", "failed", "skipped"),
        UniqueConstraint("tenant_id", "kind", "ref_id"),
        Index("ix_notification_pick", "tenant_id", "status", "not_before"),
    )


class Booking(Base):
    """A trial-class seat (WP18). The slot is a catalog row; one confirmed booking per conversation."""

    __tablename__ = "booking"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    conversation_id: Mapped[UUID] = mapped_column(ForeignKey("conversation.id"))
    contact_id: Mapped[UUID] = mapped_column(ForeignKey("contact.id"))
    slot_code: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(Text, server_default="confirmed")
    actor: Mapped[str] = mapped_column(Text)
    run_id: Mapped[UUID | None]
    created_at: Mapped[datetime] = created()
    cancelled_at: Mapped[datetime | None]
    cancelled_by: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (
        _enum("status", "confirmed", "cancelled"),
        Index("ix_booking_slot", "tenant_id", "slot_code", "status"),
        Index("uq_booking_one_live", "tenant_id", "conversation_id", unique=True,
              postgresql_where=sql_text("status = 'confirmed'")),
    )


class StaffTask(Base):
    """A cron-made to-do for staff (WP19): the morning list of customers to look after. Ids and counts
    only; names are read at view time under RLS."""

    __tablename__ = "staff_task"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    kind: Mapped[str] = mapped_column(Text)
    for_date: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="open")
    done_by: Mapped[str | None] = mapped_column(Text)
    done_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("kind", "morning_list"),
        _enum("status", "open", "done"),
        UniqueConstraint("tenant_id", "sandbox_id", "kind", "for_date"),
    )


class Digest(Base):
    """The owner's weekly and monthly numbers (WP19), built by a template from counts: no text, no LLM."""

    __tablename__ = "digest"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    kind: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    payload: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("kind", "weekly", "monthly"),
        UniqueConstraint("tenant_id", "sandbox_id", "kind", "period_start"),
    )


class Class(Base):
    """A class (WP38): the one thing a teacher sees. It points at up to two sandboxes: `recap_sandbox_id` (lesson_recap: the recordings in
    `source_ref`, the recaps to `notify_target_id`) and `grader_sandbox_id` (classroom_grader: the Classroom course `course_id`, read with
    `classroom_account_id` or the secret in `classroom_secret_enc`). Its lessons and assignments hang under it.
    The two policies are columns, not JSON. `recap_mode`: auto = a finished recap goes out at once, review = it waits for a person.
    `grading_mode`: manual = the AI grades only when asked, review = it proposes and a person decides, auto_write = it also writes the grade
    to Classroom when every check passes. Both default to the careful choice (DESIGN 2026-10-22: a person approves)."""

    __tablename__ = "class"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    name: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    listed: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))  # false: a source made on the command line, kept because lessons point at it, not shown as a class
    created_at: Mapped[datetime] = created()
    recap_sandbox_id: Mapped[UUID | None] = mapped_column(ForeignKey("sandbox.id"))
    grader_sandbox_id: Mapped[UUID | None] = mapped_column(ForeignKey("sandbox.id"))
    source_kind: Mapped[str | None] = mapped_column(Text)  # of the recordings: drive | local | upload
    source_ref: Mapped[str | None] = mapped_column(Text)  # folder id, or a path on the worker's disk
    drive_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("google_account.id"))  # reads the Drive folder
    owned: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))  # the folder was made by Cortex
    source_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # None when `drive_account_id` holds the sign-in
    notify_target_id: Mapped[UUID | None] = mapped_column(ForeignKey("notify_target.id"))  # the class's own team channel for its recaps
    classroom_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("google_account.id"))  # who acts in Classroom (posts recaps, reads work)
    course_id: Mapped[str | None] = mapped_column(Text)
    course_name: Mapped[str | None] = mapped_column(Text)  # as the teacher saw it when choosing, so the console shows it without asking Google
    auth_kind: Mapped[str | None] = mapped_column(Text)
    subject: Mapped[str | None] = mapped_column(Text)
    classroom_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # None when `classroom_account_id` holds the sign-in
    recap_mode: Mapped[str] = mapped_column(Text, server_default="review")
    grading_mode: Mapped[str] = mapped_column(Text, server_default="review")
    assignment_post_mode: Mapped[str] = mapped_column(Text, server_default="manual")  # reserved: posting assignments by itself is not built
    drive_account: Mapped["GoogleAccount | None"] = relationship(lazy="joined", foreign_keys=[drive_account_id])
    classroom_account: Mapped["GoogleAccount | None"] = relationship(lazy="joined", foreign_keys=[classroom_account_id])
    __table_args__ = (
        _enum("source_kind", "drive", "local", "upload"),
        _enum("auth_kind", "delegated", "oauth"),
        _enum("recap_mode", "auto", "review"),
        _enum("grading_mode", "manual", "review", "auto_write"),
        _enum("assignment_post_mode", "manual"),
        UniqueConstraint("tenant_id", "recap_sandbox_id", "source_kind", "source_ref"),
        UniqueConstraint("tenant_id", "grader_sandbox_id", "course_id"),
    )


class ClassKind(Base):
    """A kind of class (loại lớp), named by the business: it owns assignment templates. The compose form asks for the kind when a template is picked; no class points at a kind."""

    __tablename__ = "class_kind"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)


class AssignmentTemplate(Base):
    """A ready-made assignment of a class kind (bài tập mẫu): the same fields as the compose form, all optional, so picking it fills the form
    and the teacher finishes it. Nothing here is checked as a whole assignment; that happens when the form is saved. Dates, students and the
    topic's Classroom id are not kept: they belong to one posting of one class."""

    __tablename__ = "assignment_template"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    kind_id: Mapped[UUID] = mapped_column(ForeignKey("class_kind.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    max_points: Mapped[int | None]
    criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    answer_key: Mapped[str | None] = mapped_column(Text)
    check_prompt: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    topic_name: Mapped[str | None] = mapped_column(Text)
    materials: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))  # as pasted: {url, title, share}
    created_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("kind_id", "name"), Index("ix_assignment_template_kind", "tenant_id", "kind_id", "created_at"))


class Assignment(Base):
    """A piece of course work of a class (WP38), from the moment it is a draft to the work in Classroom. `origin`: app = Cortex made it in
    Classroom, so a grade can be written back; classroom = a teacher made it there, Cortex only reads. The grading guide (`criteria`, `answer_key`,
    `check_prompt`) lives here: no criteria, no grading. `state`: draft (not in Classroom) -> created | rejected | failed; created -> deleted (removed from Classroom too)."""

    __tablename__ = "assignment"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("class.id"))
    coursework_id: Mapped[str | None] = mapped_column(Text)  # Classroom's id; None while it is a draft
    origin: Mapped[str] = mapped_column(Text, server_default="app")
    authored_by: Mapped[str | None] = mapped_column(Text)  # teacher | ai
    state: Mapped[str] = mapped_column(Text, server_default="draft")
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    max_points: Mapped[float | None] = mapped_column(Numeric(8, 2))
    due_at: Mapped[datetime | None]
    publish: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    materials: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=sql_text("'[]'::jsonb"))  # Drive files and links attached to the work
    criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    answer_key: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)  # of a spoken answer, so the speech model is not forced into the wrong one
    check_prompt: Mapped[str | None] = mapped_column(Text)  # the teacher's own words on HOW to check this work against the answer key
    topic_id: Mapped[str | None] = mapped_column(Text)  # Classroom's topic the work is filed under, and its name as the teacher chose it
    topic_name: Mapped[str | None] = mapped_column(Text)
    scheduled_at: Mapped[datetime | None]  # Classroom publishes the work itself at this time (it sits in Classroom as a draft until then)
    assignees: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)  # [{id, name}] when only some students get it; None = the whole class
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("origin", "app", "classroom"),
        _enum("authored_by", "teacher", "ai"),
        _enum("state", "draft", "created", "rejected", "failed", "deleted"),
        UniqueConstraint("tenant_id", "class_id", "coursework_id"),
        Index("ix_assignment_class", "tenant_id", "class_id", "created_at"),
    )


class GoogleAccount(Base):
    """One Google sign-in a person made in the console (WP37): the refresh token (Fernet-encrypted, with the OAuth client it was issued to)
    and the permissions Google really granted. Classroom courses and Drive targets point at it, so a revoked sign-in is fixed in one place and
    one teacher can serve several sources. `revoked`: the secret is wiped and every source that uses it reports "needs reconnecting"."""

    __tablename__ = "google_account"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    label: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'"))
    secret_enc: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    connected_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("status", "active", "revoked"), UniqueConstraint("tenant_id", "label"))


class DriveTarget(Base):
    """A teacher's own Google Drive that recordings are stored in (WP36): their OAuth sign-in (Fernet-encrypted, with the `drive.file` permission,
    so Cortex sees only what it creates) and the id of the folder Cortex made there. The file is theirs; Cortex keeps only the words."""

    __tablename__ = "drive_target"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    label: Mapped[str] = mapped_column(Text)  # what the uploader picks: "Drive của cô Lan"
    secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # None when `google_account_id` holds the sign-in
    google_account_id: Mapped[UUID | None] = mapped_column(ForeignKey("google_account.id"))
    folder_id: Mapped[str | None] = mapped_column(Text)
    folder_adopted: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))  # the folder was the teacher's own (the watched one), not made by Cortex
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    account: Mapped["GoogleAccount | None"] = relationship(lazy="joined")  # loaded with the row, so a job needs no second query to sign in
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("tenant_id", "sandbox_id", "label"),)


class Lesson(Base):
    """One recording and what came of it. `transcript` and `recap` are the business's own text under RLS; the
    supervisor's views never select them. `status`: queued -> working -> done | failed (3 attempts)."""

    __tablename__ = "lesson"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    class_id: Mapped[UUID] = mapped_column(ForeignKey("class.id"))
    released_at: Mapped[datetime | None]  # the recap may go out (Mezon, Classroom) only once set: at once for recap_mode auto, on a person's click for review
    released_by: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)  # vi | en | auto, chosen at upload; None: the settings' default
    drive_target_id: Mapped[UUID | None] = mapped_column(ForeignKey("drive_target.id"))  # set: the recording goes to that Drive, and the local copy is dropped
    drive_file_id: Mapped[str | None] = mapped_column(Text)
    drive_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    claimed_at: Mapped[datetime | None]
    transcript: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # what each piece of a long transcript yielded (WP32): a retry skips them
    recap: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    classroom_post_id: Mapped[str | None] = mapped_column(Text)  # the announcement made in the class's Classroom course; set once, so a recap is never posted twice
    classroom_error: Mapped[str | None] = mapped_column(Text)  # why the last post failed (a short code)
    classroom_attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None]
    __table_args__ = (
        _enum("status", "queued", "working", "done", "failed"),
        UniqueConstraint("tenant_id", "sandbox_id", "file_id"),
        Index("ix_lesson_pick", "tenant_id", "status", "created_at"),
    )


class GradeItem(Base):
    """One student's submission and what became of it (WP33). status: pending (a class in `manual` mode waits for a click) -> queued -> working
    -> proposed (the AI suggested a grade, a teacher has not looked) -> approved | rejected; or skipped / failed with a code in `error`. In an
    `auto_write` class a clean suggestion is approved at once (`decided_by` = `auto`). `written_at` is set only when
    the grade went to Classroom. `content` is the student's work: personal data of a child, under RLS, never in a log."""

    __tablename__ = "grade_item"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    assignment_id: Mapped[UUID] = mapped_column(ForeignKey("assignment.id"))
    submission_id: Mapped[str] = mapped_column(Text)
    student_ref: Mapped[str] = mapped_column(Text)
    student_name: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)  # the submission in Classroom, for the teacher
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    claimed_at: Mapped[datetime | None]
    content: Mapped[str | None] = mapped_column(Text)
    content_kind: Mapped[str | None] = mapped_column(Text)  # what it was read from: text, pdf, docx, audio, video (comma separated)
    proposal: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    final: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    finished_at: Mapped[datetime | None]
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    written_at: Mapped[datetime | None]
    write_mode: Mapped[str | None] = mapped_column(Text)  # what the decision did in Classroom: none | draft | return
    __table_args__ = (
        _enum("status", "pending", "queued", "working", "proposed", "approved", "rejected", "skipped", "failed"),
        CheckConstraint("write_mode IS NULL OR write_mode in ('none', 'draft', 'return')", name="write_mode"),
        UniqueConstraint("tenant_id", "sandbox_id", "assignment_id", "submission_id"),
        Index("ix_grade_item_pick", "tenant_id", "status", "created_at"),
        Index("ix_grade_item_assignment", "tenant_id", "assignment_id", "status"),
    )


class Proposal(Base):
    """What the supervisor (AI tổng) suggests; only a person's click changes anything (DESIGN §5.6).
    `evidence` holds numbers and enum codes read from the metadata views: never a word a customer wrote."""

    __tablename__ = "proposal"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    kind: Mapped[str] = mapped_column(Text)
    signal: Mapped[str] = mapped_column(Text)
    target: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    evidence: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("kind", "rollback_skill", "pause_sandbox", "review_skill", "tune_skill"),
        _enum("status", "pending", "accepted", "dismissed", "stale"),
        Index("uq_proposal_open", "tenant_id", "sandbox_id", "signal", sql_text("coalesce(target->>'skill', '')"),
              unique=True, postgresql_where=sql_text("status = 'pending'")),
    )


class AuditEvent(Base):
    """Who did what, when, from where (DESIGN §5.14). Append-only: the app role has no UPDATE/DELETE and a trigger refuses both
    for everyone. Each row chains the hash of the one before it, so a removed or edited row is detectable. `tenant_id` NULL is
    platform scope (a sign-in with a key that matches no business). Never holds a customer's words, a draft or a secret."""

    __tablename__ = "audit_event"
    id: Mapped[UUID] = pk()
    seq: Mapped[int] = mapped_column(BigInteger, server_default=sql_text("0"))  # identity in the migration: the chain order
    tenant_id: Mapped[UUID | None]
    at: Mapped[datetime] = created()
    actor: Mapped[str] = mapped_column(Text)
    actor_role: Mapped[str] = mapped_column(Text, server_default="system")
    category: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    result: Mapped[str] = mapped_column(Text, server_default="success")
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    object_label: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=sql_text("'{}'::jsonb"))
    prev_hash: Mapped[str | None] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(Text)
    __table_args__ = (_enum("result", "success", "denied", "failed", "pending"),)


class ToolConnector(Base):
    """A read-only HTTP source the business configured (T1 `http_readonly`, DESIGN §5.8). The config is
    pinned by `pin_sha256`; a row whose config no longer hashes to the pin is refused at call time."""

    __tablename__ = "tool_connector"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    sandbox_id: Mapped[UUID] = mapped_column(ForeignKey("sandbox.id"))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text, server_default="http_readonly")
    source: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    description: Mapped[str] = mapped_column(Text, server_default="")
    secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)  # Fernet token of the auth header value
    pin_sha256: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # soft lock: hidden, restorable
    deleted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    alert: Mapped[str | None] = mapped_column(Text, nullable=True)  # why it stopped by itself (the pinned definition changed)
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("kind", "http_readonly", "mcp"),
        _enum("status", "active", "disabled"),
        UniqueConstraint("tenant_id", "sandbox_id", "name"),
    )


class AppUser(Base):
    """A person who signs in to the console. Email is unique across all businesses (it finds the business); the password is
    only ever stored as a salted scrypt hash. Accounts are disabled, never deleted: the audit log keeps pointing at them."""

    __tablename__ = "app_user"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text)
    staff_ref: Mapped[str] = mapped_column(Text)  # the name drafts and conversations carry (`staff:nv1`); unique per business
    password_hash: Mapped[str] = mapped_column(Text)
    password_changed_at: Mapped[datetime] = created()
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    birth_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    national_id_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet; read only by the owner's account screen
    # two-step sign-in (migration 0049): see auth/mfa.py. The secret is Fernet like the ID number; the recovery codes are kept only as hashes.
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # set up but not yet confirmed with a code
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mfa_recovery: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))  # sign-in tokens carry this; raising it ends every one of them
    status: Mapped[str] = mapped_column(Text, server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()


class ClassTeacher(Base):
    """Who is in charge of a class (WP46). A `teacher` account sees and runs only the classes it has a row for; `staff` and `owner` reach every
    class and need none. Goes with the class; an account is never deleted, only disabled, so its rows stay for when it comes back."""

    __tablename__ = "class_teacher"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    class_id: Mapped[UUID] = mapped_column(ForeignKey("class.id", ondelete="CASCADE"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    assigned_by: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (UniqueConstraint("class_id", "user_id"),)


class AuthSession(Base):
    """A signed-in browser: what the list of devices shows and what signing one out marks. The cookie is a signed token naming this row
    (`sid`). The refresh token's secret is kept only as a hash and swapped on every use; nothing here can make a token, so a database leak is not a set of working sessions."""

    __tablename__ = "auth_session"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = created()
    last_seen_at: Mapped[datetime] = created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # the absolute end of this sign-in
    refresh_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # sha256 of the current refresh token's secret; the token itself is only in the browser
    refresh_prev_hash: Mapped[str | None] = mapped_column(Text, nullable=True)  # the one before, to tell two tabs racing from a stolen copy
    refresh_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class LoginThrottle(Base):
    """Failed-sign-in counters keyed by a hash (per address, per account), so guessing is slowed whether or not the account exists."""

    __tablename__ = "login_throttle"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, server_default="0")
    first_at: Mapped[datetime] = created()
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PasswordReset(Base):
    """A link sent by email so a person who lost their password can choose a new one. Only a hash of the token is kept; it works once
    and for a short time (0039). Looked up by that hash before the business is known, like a session."""

    __tablename__ = "password_reset"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = created()
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)


class PlatformAdmin(Base):
    """The operator of the server (WP47, DESIGN §5.16), not a person of any business: no `tenant_id`, so no RLS, like `tenant` and
    `login_throttle`. Signs in at /app/admin with a password and, always, a TOTP code. Same MFA columns as `app_user` so `auth/mfa.py`
    works on both. Disabled, never deleted."""

    __tablename__ = "platform_admin"
    id: Mapped[UUID] = pk()
    email: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(Text)
    password_hash: Mapped[str] = mapped_column(Text)
    mfa_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mfa_recovery: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    token_version: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("status", "active", "disabled"),)


# Tables created by migrations after 0001 (0001 builds only the v0 schema from these models).
WAVE2_TABLES = {"contact_fact", "deal", "outbox", "notify_target", "notification", "booking",
                "staff_task", "digest", "tool_connector", "proposal", "audit_event", "app_user", "auth_session", "login_throttle", "password_reset",
                "lesson_source", "lesson", "drive_target", "classroom_source", "grading_guide", "grade_item", "assignment_draft", "google_account", "class", "assignment", "class_kind", "assignment_template", "class_teacher", "platform_admin"}
# Supervisor views (no free-text column). DESIGN §5.6. view -> (table, columns it reads).
SUPERVISOR_VIEWS = {
    "supervisor_fact_view": ("contact_fact", ["tenant_id", "kind", "source", "status", "created_at"]),
    "supervisor_deal_view": ("deal", ["tenant_id", "status", "value", "currency", "occurred_at",
                                      "linked"]),
    "supervisor_outbox_view": ("outbox", ["tenant_id", "status", "reason", "actor", "created_at",
                                          "sent_at"]),
}

# Columns cl_supervisor may read (no free text). DESIGN §5.6.
SUPERVISOR_RUN_COLUMNS = [
    c.name for c in TriggerRun.__table__.columns if c.name not in ("job_id",)
]
