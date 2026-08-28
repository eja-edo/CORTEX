"""Mezon DM delivery.

The whole backend side of reaching a user on Mezon. Per the delivery
layer's acceptance criterion (docs/planning-v3.md §XI): this file plus one
`register(...)` line in `registry.py`, and nothing in `attention_gate.py`,
`notifications.py`, or `delivery_worker.py` changes.

**Why it goes over HTTP to the bot instead of talking to Mezon directly.**
The Mezon SDK is TypeScript-only, and the backend is Python — there is no
choice about the bot being a separate process. Given that, the two ways to
reach it are an HTTP call or a Redis publish. HTTP wins because the reply
carries an outcome: a 5xx becomes `retry()`, a "user blocked the bot"
becomes `dead_address()` and the delivery layer disables the channel by
itself. A fire-and-forget publish would throw away the retry and
backoff machinery F0 was built to provide, at the last hop.

`default_min_level = RECOMMEND` rather than INFORM: a DM is more intrusive
than a badge in a tab the user may not have open. `task.at_risk` (ASK) and
`task.overdue`/`task.blocked_cascade` (RECOMMEND) get through; `task.stale`,
`day.review` and `schedule.starts_soon` (INFORM) stay in-app. A user who
wants everything can lower their own floor — the default is the quiet one,
matching boundary #2.
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import settings
from app.database_async import make_async_sessionmaker
from app.models import AttentionChannel, AttentionLevel, UserChannel
from app.services.delivery.base import DeliveryPayload, DeliveryResult
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Lazily created, then reused for the life of the process. `send()` always
# runs on `DeliveryWorker`'s dedicated thread/event loop (Mezon's
# `inline = False`), never the FastAPI request loop, so this cannot be the
# app's shared engine (see `database_async.make_async_sessionmaker`'s
# docstring) — but recreating a whole engine+pool on every single
# notification would be wasteful, so it is cached here instead of made
# fresh per call.
_engine: AsyncEngine | None = None
_session_maker: async_sessionmaker[AsyncSession] | None = None


def _get_session_maker() -> async_sessionmaker[AsyncSession]:
    global _engine, _session_maker
    if _session_maker is None:
        _engine, _session_maker = make_async_sessionmaker()
    return _session_maker


class MezonAdapter:
    channel = AttentionChannel.MEZON
    default_min_level = AttentionLevel.RECOMMEND
    inline = False
    # A Mezon user id is a number anyone in a clan can read, so possessing
    # one proves nothing. `channel_link.redeem_link_code` is what sets
    # `verified_at`; until then the dispatcher records `skipped/unverified`
    # rather than messaging a stranger.
    requires_verification = True

    async def send(self, payload: DeliveryPayload, user_channel: UserChannel | None) -> DeliveryResult:
        if user_channel is None:
            # In-app is the only channel delivered without a row; reaching
            # here without one means a planning bug, not a transient fault,
            # so it must not be retried forever.
            return DeliveryResult.permanent("Mezon delivery requires a registered user_channel")

        if not settings.MEZON_BOT_INTERNAL_URL:
            # Deployment gap, not a bad address. `unavailable` rather than
            # `retry` so it costs no attempt: an unconfigured URL stays
            # unconfigured for as long as it takes someone to notice, and
            # burning the budget would lose every queued nudge in the
            # meantime.
            return DeliveryResult.unavailable("MEZON_BOT_INTERNAL_URL is not configured")

        # Nhắc cấp dự án về channel của dự án, nhắc cá nhân về DM (8.1).
        # Vẫn cần `user_channel` cho cả hai: nó là bằng chứng người này đã
        # liên kết Mezon và đã qua `min_level`. Không có nó thì một dự án
        # sẽ đăng vào channel thay cho một người chưa từng bật Mezon.
        project_channel_id = payload.project_channel_id

        body = {
            "mezon_user_id": user_channel.address,
            # `None` cho nhắc cá nhân — bot đọc trường này để chọn giữa
            # `sendToChannel` và `sendDirectMessage`.
            "mezon_channel_id": project_channel_id,
            "notification_id": str(payload.notification_id),
            "title": payload.title,
            "body": payload.body,
            # The digest reasons (`day.plan`, `day.review`, `task.at_risk`,
            # `task.blocked_cascade`) put their itemised detail in `content`
            # and keep `body` as the one-line summary. Sending only `body`
            # meant a DM said "3 việc đến hạn hôm nay" and never named one,
            # while the in-app card listed all three.
            "content": payload.content,
            "reason_key": payload.reason_key,
            "attention_level": payload.effective_level.value,
            "actions": payload.actions,
            "payload": payload.payload,
        }

        try:
            async with httpx.AsyncClient(timeout=settings.MEZON_BOT_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{settings.MEZON_BOT_INTERNAL_URL.rstrip('/')}/internal/deliver",
                    json=body,
                    headers={"X-Internal-API-Key": settings.INTERNAL_API_KEY},
                )
        except httpx.TimeoutException as exc:
            # The bot answered slowly or not at all. It is up but wedged, so
            # this counts as an attempt — unlike a refused connection, a
            # timeout may mean the bot is stuck on *this* delivery.
            return DeliveryResult.retry(f"timeout talking to bot: {exc}")
        except httpx.HTTPError as exc:
            # Connection refused / DNS / reset: the bot is not there at all.
            # Restarts and deploys are routine, and this says nothing about
            # the notification, so it must not consume the retry budget —
            # otherwise a deploy longer than the retry window silently loses
            # every notification created during it. See DeliveryOutcome.
            return DeliveryResult.unavailable(f"bot unreachable: {exc}")

        if response.status_code < 300:
            await self._record_system_note(user_channel.user_id, payload)
            return DeliveryResult.sent()

        detail = response.text[:300]

        if response.status_code == 410:
            # The bot's agreed signal for "this recipient is unreachable for
            # good" — blocked the bot, deleted account, DM channel refused.
            return DeliveryResult.dead_address(f"bot reported gone: {detail}")

        if response.status_code in (408, 429) or response.status_code >= 500:
            return DeliveryResult.retry(f"bot returned {response.status_code}: {detail}")

        # Any other 4xx is us sending something the bot rejects — a
        # malformed payload will be just as malformed next time.
        return DeliveryResult.permanent(f"bot returned {response.status_code}: {detail}")

    async def _record_system_note(self, user_id, payload: DeliveryPayload) -> None:
        """R5 (docs/mezon-bot-plan.md §V): everything sent through Mezon
        goes into that user's conversation history too, as `role="system"`
        — so a later chat turn can see "I already told you this" instead of
        repeating itself or being unable to answer "why didn't you say so
        earlier".

        Imported locally, not at module scope: `ConversationStore` sits in
        `app.ai.agents`, a layer above `app.services.delivery` that has no
        reason to import back down here, and a top-level import would be
        the only thing creating that edge.

        Never allowed to fail the delivery it's attached to — the DM is
        already sent by the time this runs, and a already-committed
        HTTP 2xx from the bot must not turn into a `retry()` because this
        side-write hit a transient DB error.
        """
        from app.ai.agents.conversation_store import ConversationStore

        try:
            session_maker = _get_session_maker()
            async with session_maker() as db:
                store = ConversationStore(db)
                conv = await store.get_or_create_mezon_conversation(user_id)
                note = f'Đã nhắc: "{payload.title}"' + (f" — {payload.body}" if payload.body else "")
                await store.save_message(
                    conversation_id=conv.id, role="system", content=note, source="mezon",
                )
                await db.commit()
        except Exception:
            logger.exception(
                "Could not record system note for delivered Mezon notification %s (non-fatal)",
                payload.notification_id,
            )
