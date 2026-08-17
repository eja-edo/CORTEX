"""In-app delivery — the SSE push to whatever tabs the user has open.

This is the channel that already existed, moved behind the adapter
interface unchanged. The `publish_notification*` calls it wraps used to sit
inline in `create_notification_async` / `NotificationService.create`; they
still run in exactly the same place and order, so this refactor is
behaviour-preserving for the web client by construction.

It is the one adapter with `inline = True`. Three properties make it
different in kind from every channel that will follow, and they are the
reason the distinction is a declared flag rather than a special case in
the dispatcher:

1. It is in-process. There is no network call to a third party to time out.
2. Its failure mode is not retryable. "No tab is connected" is not a
   transient error to back off from — it is the exact condition the other
   channels exist to cover, and retrying it in thirty seconds would be
   answering the wrong question.
3. It feeds a live UI, so poll-interval latency (fine for a push, fine for
   a bot message) would be a visible regression.
"""

from app.api.sse.channels.notification_events import (
    publish_notification,
    publish_notification_async,
)
from app.models import AttentionChannel, AttentionLevel, UserChannel
from app.services.delivery.base import DeliveryPayload, DeliveryResult


class InAppAdapter:
    channel = AttentionChannel.IN_APP
    # Everything the Gate decided to speak at all belongs in the in-app
    # inbox: the Notification row *is* the in-app delivery, and hiding a
    # row the user can already see in their bell menu would make the two
    # disagree.
    default_min_level = AttentionLevel.INFORM
    inline = True
    requires_verification = False

    async def send(self, payload: DeliveryPayload, user_channel: UserChannel | None) -> DeliveryResult:
        await publish_notification_async(
            user_id=str(payload.user_id),
            notification_id=str(payload.notification_id),
            title=payload.title,
            body=payload.body,
            content=payload.content,
            actions=payload.actions,
            notification_type=payload.type,
            payload=payload.payload,
            reason_key=payload.reason_key,
            attention_level=payload.attention_level.value if payload.attention_level else None,
            attention_log_id=str(payload.attention_log_id) if payload.attention_log_id else None,
        )
        # `publish_notification_async` swallows and logs its own failures
        # (broadcasting is best-effort — a dropped SSE frame must never fail
        # a notification that is already committed), so there is no error to
        # translate here. That deliberate asymmetry is why in-app never
        # returns RETRY.
        return DeliveryResult.sent()

    def send_sync(self, payload: DeliveryPayload, user_channel: UserChannel | None) -> DeliveryResult:
        """Sync twin, for `NotificationService.create`'s threadpool callers.

        The two SSE entry points cannot be collapsed into one — see
        `publish_notification`'s docstring for why guessing the caller's
        loop state is not possible — so the same split surfaces here. Only
        inline adapters ever need this; worker-driven adapters are always
        called from the worker's own event loop.
        """
        publish_notification(
            user_id=str(payload.user_id),
            notification_id=str(payload.notification_id),
            title=payload.title,
            body=payload.body,
            content=payload.content,
            actions=payload.actions,
            notification_type=payload.type,
            payload=payload.payload,
            reason_key=payload.reason_key,
            attention_level=payload.attention_level.value if payload.attention_level else None,
            attention_log_id=str(payload.attention_log_id) if payload.attention_log_id else None,
        )
        return DeliveryResult.sent()
