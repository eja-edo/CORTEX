"""Linking a chat account to a Cortex user (M1).

Two halves, deliberately on opposite sides of the trust boundary:

- `create_link_code` runs for an authenticated web session. The person is
  already proven to be themselves, so minting a code is safe.
- `redeem_link_code` runs for the bot, which knows a chat id and a code but
  cannot prove anything on its own. It is the code that carries the proof.

Doing it the other way round — typing a Mezon id into the web app — would
let anyone claim anyone else's chat account, because those ids are visible
to every member of a clan. See `ChannelLinkCode`'s docstring.
"""

import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AttentionChannel, ChannelLinkCode, UserChannel
from app.services.delivery.registry import is_registerable
from app.services.user_channels import register_channel_async
from app.utils.logger import get_logger

logger = get_logger(__name__)

CODE_LENGTH = 6


class LinkError(Exception):
    """Redemption refused. The message is safe to show a user."""


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_code() -> str:
    """Six digits from a CSPRNG.

    `secrets`, not `random`: this is a credential for the few minutes it
    lives, and `random` is seeded predictably enough that a stream of codes
    could be guessed from a couple of observed ones.
    """
    return "".join(secrets.choice("0123456789") for _ in range(CODE_LENGTH))


async def create_link_code(
    session: AsyncSession, user_id: UUID, *, channel: AttentionChannel
) -> ChannelLinkCode:
    """Mint a code for an authenticated user. Raises `LinkError` for a
    channel with no adapter — offering to link a channel that cannot
    deliver anything would be a dead end the user only discovers later."""
    if not is_registerable(channel):
        raise LinkError(f"Kênh {channel.value} chưa hỗ trợ")

    # Outstanding codes for the same channel are burned first. Otherwise a
    # user who clicks "link" three times has three live codes, and the two
    # they abandoned stay valid — three chances for a shoulder-surfer
    # instead of one.
    now = _naive_utcnow()
    stmt = select(ChannelLinkCode).where(
        ChannelLinkCode.user_id == user_id,
        ChannelLinkCode.channel == channel,
        ChannelLinkCode.used_at.is_(None),
        ChannelLinkCode.expires_at > now,
    )
    for stale in (await session.execute(stmt)).scalars().all():
        stale.expires_at = now

    row = ChannelLinkCode(
        user_id=user_id,
        channel=channel,
        code=_generate_code(),
        expires_at=now + timedelta(seconds=settings.CHANNEL_LINK_CODE_TTL_SECONDS),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def redeem_link_code(
    session: AsyncSession,
    *,
    code: str,
    channel: AttentionChannel,
    address: str,
    label: str | None = None,
) -> UserChannel:
    """Exchange a code for a verified `user_channels` row.

    Raises `LinkError` with a user-safe message on every failure path. The
    messages deliberately do not distinguish "no such code" from "expired"
    from "already used": all three mean *try again from the web app*, and
    telling an attacker which of the three they hit is free information
    about whether a code ever existed.
    """
    normalized = (code or "").strip()
    if not normalized:
        raise LinkError("Mã liên kết trống")

    now = _naive_utcnow()
    row = (
        await session.execute(
            select(ChannelLinkCode)
            .where(ChannelLinkCode.code == normalized, ChannelLinkCode.channel == channel)
            .order_by(ChannelLinkCode.created_at.desc())
            .limit(1)
        )
    ).scalars().first()

    if row is None:
        raise LinkError("Mã không hợp lệ hoặc đã hết hạn")

    row.attempts = (row.attempts or 0) + 1

    if row.used_at is not None or row.expires_at <= now:
        await session.commit()
        raise LinkError("Mã không hợp lệ hoặc đã hết hạn")

    # Marked used before the channel is registered, and committed on the
    # way out: if registration then fails, the code is still spent. A code
    # that survives a failed redemption is a code that can be replayed.
    row.used_at = now
    row.redeemed_address = address
    await session.commit()

    user_channel = await register_channel_async(
        session,
        row.user_id,
        channel=channel,
        address=address,
        label=label,
    )

    # The code *is* the proof of ownership, so redemption is what verifies
    # the address — `register_channel_async` leaves it unverified for any
    # channel whose adapter requires proof, and this is that proof.
    if user_channel.verified_at is None:
        user_channel.verified_at = now
        await session.commit()
        await session.refresh(user_channel)

    logger.info(
        "Linked %s channel for user %s (channel_id=%s)",
        channel.value, row.user_id, user_channel.id,
    )
    return user_channel
