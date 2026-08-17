"""Managing a user's registered delivery routes (`user_channels`).

The settings page for this is a place to **turn things off** — boundary #2
from docs/planning-v3.md. Registration comes from the client that owns the
address (a browser handing over its own push subscription, a bot linking a
chat), and takes effect immediately at the adapter's default floor. A user
who never opens the page still gets delivered to; the page is where they
raise a floor, rename a device, or revoke one.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttentionChannel, AttentionLevel, UserChannel
from app.services.delivery.registry import get_adapter, is_registerable


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def address_hint(address: str) -> str:
    """A short, non-reversible-enough tail of the address.

    Push endpoints are URLs that act as bearer capabilities — anyone
    holding one can send that browser a notification — so the settings API
    echoes a hint, not the value. Enough to disambiguate two rows, useless
    to anyone who intercepts the response.
    """
    if len(address) <= 8:
        return "…" + address[-4:] if len(address) > 4 else "…"
    return "…" + address[-8:]


async def list_channels_async(session: AsyncSession, user_id: UUID) -> list[UserChannel]:
    stmt = (
        select(UserChannel)
        .where(UserChannel.user_id == user_id)
        .order_by(UserChannel.created_at.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def resolve_channel_async(
    session: AsyncSession, *, channel: AttentionChannel, address: str
) -> UserChannel | None:
    """Which Cortex user is this chat account? `None` if not linked.

    Only ever matches a **verified** row. An unverified row means someone
    claimed the address without proving it (see `ChannelLinkCode`), and
    treating that as an identity would turn the linking step into
    decoration — anyone could type a stranger's Mezon id into the settings
    API and then talk to Cortex as them.
    """
    stmt = select(UserChannel).where(
        UserChannel.channel == channel,
        UserChannel.address == address,
        UserChannel.verified_at.is_not(None),
    )
    return (await session.execute(stmt)).scalars().first()


async def register_channel_async(
    session: AsyncSession,
    user_id: UUID,
    *,
    channel: AttentionChannel,
    address: str,
    label: str | None = None,
    config: dict[str, Any] | None = None,
    min_level: AttentionLevel | None = None,
) -> UserChannel:
    """Register (or refresh) one route. Raises `ValueError` if the channel
    has no adapter — letting a user register a device that provably cannot
    receive anything is a support ticket, not a feature.

    Re-registering the same address updates the existing row rather than
    adding a second one. Browsers rotate push subscriptions and re-send
    them on every load; without this, one user would accumulate a row per
    session and get one duplicate notification per row. It deliberately
    does **not** reset `min_level` or `enabled` — those are the user's
    settings, and a routine re-registration silently undoing "only urgent
    things on this device" would be the worst kind of bug to notice.
    """
    if not is_registerable(channel):
        raise ValueError(f"Channel {channel.value} has no delivery adapter")

    adapter = get_adapter(channel)
    assert adapter is not None  # is_registerable already established this

    existing = (
        await session.execute(
            select(UserChannel).where(
                UserChannel.user_id == user_id,
                UserChannel.channel == channel,
                UserChannel.address == address,
            )
        )
    ).scalars().first()

    if existing is not None:
        if label is not None:
            existing.label = label
        if config is not None:
            existing.config = config
        if min_level is not None:
            existing.min_level = min_level
        if not adapter.requires_verification and existing.verified_at is None:
            existing.verified_at = _naive_utcnow()
        await session.commit()
        await session.refresh(existing)
        return existing

    row = UserChannel(
        user_id=user_id,
        channel=channel,
        address=address,
        label=label,
        config=config or {},
        min_level=min_level or adapter.default_min_level,
        # Channels whose registration is itself proof of possession are
        # verified on the spot; the rest wait for an explicit confirmation
        # step, and the dispatcher skips them until then.
        verified_at=None if adapter.requires_verification else _naive_utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def update_channel_async(
    session: AsyncSession,
    user_id: UUID,
    channel_id: UUID,
    *,
    enabled: bool | None = None,
    min_level: AttentionLevel | None = None,
    label: str | None = None,
) -> UserChannel | None:
    row = await session.get(UserChannel, channel_id)
    if row is None or row.user_id != user_id:
        return None
    if enabled is not None:
        row.enabled = enabled
    if min_level is not None:
        row.min_level = min_level
    if label is not None:
        row.label = label
    await session.commit()
    await session.refresh(row)
    return row


async def delete_channel_async(session: AsyncSession, user_id: UUID, channel_id: UUID) -> bool:
    row = await session.get(UserChannel, channel_id)
    if row is None or row.user_id != user_id:
        return False
    await session.delete(row)
    await session.commit()
    return True
