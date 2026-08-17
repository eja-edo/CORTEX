"""Which channels actually have a delivery path today.

`AttentionChannel` declares more values than this registry holds, on
purpose (see that enum's docstring): the enum is the schema's vocabulary,
this is the set of routes that exist in code right now. A `user_channels`
row naming a channel absent from here is a defined state — the dispatcher
records `skipped/no_adapter` rather than failing — which is what makes it
safe to ship the enum values ahead of the adapters.
"""

from app.models import AttentionChannel
from app.services.delivery.base import DeliveryChannelAdapter
from app.services.delivery.in_app import InAppAdapter
from app.services.delivery.mezon import MezonAdapter

_ADAPTERS: dict[AttentionChannel, DeliveryChannelAdapter] = {}


def register(adapter: DeliveryChannelAdapter) -> None:
    _ADAPTERS[adapter.channel] = adapter


def get_adapter(channel: AttentionChannel) -> DeliveryChannelAdapter | None:
    return _ADAPTERS.get(channel)


def registered_channels() -> list[AttentionChannel]:
    return list(_ADAPTERS)


def is_registerable(channel: AttentionChannel) -> bool:
    """Can a user add a `user_channels` row for this channel?

    The settings API refuses channels with no adapter — a user registering
    a device that provably cannot receive anything is a support ticket, not
    a feature. In-app is excluded for the opposite reason: every user has
    it implicitly and there is nothing to register.
    """
    return channel in _ADAPTERS and channel is not AttentionChannel.IN_APP


# Adapters register at import time; `app.services.delivery` imports this
# module, so any importer of the package gets a populated registry. Adding
# a channel is one import plus one line here — see base.py's contract.
register(InAppAdapter())
register(MezonAdapter())
