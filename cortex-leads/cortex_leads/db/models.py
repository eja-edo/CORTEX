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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates

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
NO_RLS = {"tenant", "connector", "api_key"}


class Tenant(Base):
    __tablename__ = "tenant"
    id: Mapped[UUID] = pk()
    name: Mapped[str] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, server_default="Asia/Ho_Chi_Minh")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("status", "active", "paused"),)


class Sandbox(Base):
    __tablename__ = "sandbox"
    id: Mapped[UUID] = pk()
    tenant_id: Mapped[UUID] = tid()
    name: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text, server_default="customer_care")
    profile_ref: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    isolation: Mapped[str] = mapped_column(Text, server_default="logical")
    budget: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    send_mode: Mapped[str] = mapped_column(Text, server_default="manual")
    domain_pack: Mapped[dict[str, Any]] = mapped_column(server_default=sql_text("'{}'::jsonb"))
    business_hours: Mapped[dict[str, Any]] = mapped_column(
        server_default=sql_text('\'{"start":"08:00","end":"21:00"}\'::jsonb'))
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
    __table_args__ = (_enum("role", "staff", "owner", "supervisor"),)


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
    address: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("true"))
    created_at: Mapped[datetime] = created()
    __table_args__ = (_enum("kind", "telegram"), UniqueConstraint("tenant_id", "kind", "address"))


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
        _enum("kind", "handoff", "booking", "task", "digest", "proposal"),
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
    """The owner's weekly numbers (WP19), built by a template from counts: no text, no LLM."""

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
        _enum("kind", "weekly"),
        UniqueConstraint("tenant_id", "sandbox_id", "kind", "period_start"),
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
    created_at: Mapped[datetime] = created()
    __table_args__ = (
        _enum("kind", "http_readonly", "mcp"),
        _enum("status", "active", "disabled"),
        UniqueConstraint("tenant_id", "sandbox_id", "name"),
    )


# Tables created by migrations after 0001 (0001 builds only the v0 schema from these models).
WAVE2_TABLES = {"contact_fact", "deal", "outbox", "notify_target", "notification", "booking",
                "staff_task", "digest", "tool_connector", "proposal"}
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
