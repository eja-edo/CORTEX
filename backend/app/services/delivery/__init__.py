"""Delivery layer — how a Notification reaches a user (bước 0).

Splits the two things `create_notification_async` used to do in one
breath: persist the notification (unchanged, still the durable in-app
record) and get it in front of the user (this package). Before the split,
"in front of the user" meant one hardcoded SSE call, so a nudge computed
while the user had no browser tab open reached nobody — the Attention
Gate's five careful steps ended in a message no one received.

    Gate (whether to speak)  →  Notification row  →  dispatcher (where)
                                                        ├── in_app: inline SSE
                                                        └── everything else:
                                                            outbox → DeliveryWorker

Adding a channel is: one module here implementing `DeliveryChannelAdapter`,
one `register(...)` line in `registry.py`. Nothing in `attention_gate.py`,
`notifications.py`, or `delivery_worker.py` should need to change — that is
the acceptance criterion for the layer, not just a style preference.
"""

from app.services.delivery.base import (
    DeliveryChannelAdapter,
    DeliveryOutcome,
    DeliveryPayload,
    DeliveryResult,
)
from app.services.delivery.dispatcher import (
    PlannedDelivery,
    plan_deliveries_async,
    plan_deliveries_sync,
    run_inline_deliveries_async,
    run_inline_deliveries_sync,
)
from app.services.delivery.registry import (
    get_adapter,
    is_registerable,
    register,
    registered_channels,
)

__all__ = [
    "DeliveryChannelAdapter",
    "DeliveryOutcome",
    "DeliveryPayload",
    "DeliveryResult",
    "PlannedDelivery",
    "get_adapter",
    "is_registerable",
    "plan_deliveries_async",
    "plan_deliveries_sync",
    "register",
    "registered_channels",
    "run_inline_deliveries_async",
    "run_inline_deliveries_sync",
]
