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

from app.config import settings
from app.models import AttentionChannel, AttentionLevel, UserChannel
from app.services.delivery.base import DeliveryPayload, DeliveryResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
            # Deployment gap, not a bad address: retry so deliveries queue
            # up and drain once the bot URL is configured, instead of being
            # marked failed and lost.
            return DeliveryResult.retry("MEZON_BOT_INTERNAL_URL is not configured")

        body = {
            "mezon_user_id": user_channel.address,
            "notification_id": str(payload.notification_id),
            "title": payload.title,
            "body": payload.body,
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
            return DeliveryResult.retry(f"timeout talking to bot: {exc}")
        except httpx.HTTPError as exc:
            # The bot being down is the common case here (restart, deploy).
            # Retryable by definition.
            return DeliveryResult.retry(f"transport error talking to bot: {exc}")

        if response.status_code < 300:
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
