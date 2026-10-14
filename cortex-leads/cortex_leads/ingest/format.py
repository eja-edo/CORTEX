"""Cortex Event Format v1 (DESIGN §5.2). Strict: unknown fields are rejected, not ignored."""
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FORMAT = "cortex.event/1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Channel(_Strict):
    kind: str = Field(min_length=1)
    account_ref: str | None = None


class ConversationRef(_Strict):
    external_id: str = Field(min_length=1, max_length=255)


class ContactRef(_Strict):
    external_id: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    phone: str | None = None


class Sender(_Strict):
    role: Literal["customer", "staff", "bot"]


class StaffRef(_Strict):
    external_id: str | None = None


class DealContactRef(_Strict):
    connector_id: str
    external_id: str


class DealContact(_Strict):
    phone: str | None = None
    ref: DealContactRef | None = None


class DealPayload(_Strict):
    external_id: str = Field(min_length=1, max_length=255)  # stable id of the deal (event id is the dedupe key)
    status: Literal["booked", "won", "lost", "cancelled"]
    value: float | None = None
    currency: str = "VND"


class Event(_Strict):
    type: Literal["message.created", "conversation.updated", "contact.updated", "deal.updated"]
    external_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    # Required for every type but deal.updated (a deal is not inside a chat channel).
    channel: Channel | None = None
    conversation: ConversationRef | None = None
    contact: ContactRef | DealContact
    sender: Sender | None = None
    deal: DealPayload | None = None
    staff: StaffRef = StaffRef()
    text: str | None = None
    attachments: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}  # never used for decisions

    @model_validator(mode="after")
    def _check(self) -> "Event":
        if self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must carry a timezone")
        if self.type == "deal.updated":
            if self.deal is None or not isinstance(self.contact, DealContact) \
                    or not (self.contact.phone or self.contact.ref):
                raise ValueError("deal.updated needs deal and contact {phone|ref}")
            return self
        if self.deal is not None or None in (self.channel, self.conversation, self.sender) \
                or not isinstance(self.contact, ContactRef):
            raise ValueError("channel, conversation, contact.external_id and sender are required")
        if self.type == "message.created" and not (self.text or self.attachments):
            raise ValueError("message.created needs text or attachments")
        return self


class EventBatch(_Strict):
    format: Literal["cortex.event/1"]
    events: list[Event]


class EventEnvelope(_Strict):
    """Envelope only: events stay raw so one bad event is `rejected` without failing the batch."""

    format: Literal["cortex.event/1"]
    events: list[Any]
