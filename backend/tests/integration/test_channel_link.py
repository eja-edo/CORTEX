"""Integration tests for chat-account linking (M1).

The thing under test is a security boundary, not a convenience: a Mezon
user id is a number visible to everyone in a clan, so the only thing
standing between an attacker and someone else's Cortex account is that a
code must be minted by an authenticated session and can be spent once.
Every test below is one way that could go wrong.
"""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.database_async import make_async_sessionmaker
from app.models import AttentionChannel, ChannelLinkCode, UserChannel
from app.services.channel_link import LinkError, create_link_code, redeem_link_code
from tests.integration.isolated_user import ensure_isolated_user


def _naive_utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@pytest_asyncio.fixture
async def user_id():
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def db(user_id):
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as session:
        yield session
        await session.execute(delete(ChannelLinkCode).where(ChannelLinkCode.user_id == user_id))
        await session.execute(delete(UserChannel).where(UserChannel.user_id == user_id))
        await session.commit()
    await engine.dispose()


@pytest.mark.asyncio
async def test_minting_produces_a_six_digit_code(db, user_id):
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)

    assert len(row.code) == 6
    assert row.code.isdigit()
    assert row.used_at is None
    assert row.expires_at > _naive_utcnow()


@pytest.mark.asyncio
async def test_redeeming_links_and_verifies_the_channel(db, user_id):
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)

    channel = await redeem_link_code(
        db, code=row.code, channel=AttentionChannel.MEZON,
        address="mezon-user-0001", label="Mezon cá nhân",
    )

    assert channel.user_id == user_id
    assert channel.address == "mezon-user-0001"
    # The code is the proof of ownership, so redemption is what verifies —
    # otherwise the Mezon adapter (requires_verification=True) would skip
    # every delivery to a freshly linked account.
    assert channel.verified_at is not None
    assert channel.enabled is True


@pytest.mark.asyncio
async def test_a_code_cannot_be_spent_twice(db, user_id):
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    await redeem_link_code(db, code=row.code, channel=AttentionChannel.MEZON, address="addr-1")

    with pytest.raises(LinkError):
        await redeem_link_code(db, code=row.code, channel=AttentionChannel.MEZON, address="attacker")


@pytest.mark.asyncio
async def test_expired_code_is_refused(db, user_id):
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    row.expires_at = _naive_utcnow() - timedelta(seconds=1)
    await db.commit()

    with pytest.raises(LinkError):
        await redeem_link_code(db, code=row.code, channel=AttentionChannel.MEZON, address="addr-2")


@pytest.mark.asyncio
async def test_unknown_code_is_refused(db, user_id):
    with pytest.raises(LinkError):
        await redeem_link_code(db, code="000000", channel=AttentionChannel.MEZON, address="addr-3")


@pytest.mark.asyncio
async def test_code_is_scoped_to_its_channel(db, user_id):
    """A code minted for Mezon must not link a Telegram account. Without
    the channel in the lookup, one leaked code would work on whichever
    channel the attacker prefers."""
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)

    with pytest.raises(LinkError):
        await redeem_link_code(db, code=row.code, channel=AttentionChannel.TELEGRAM, address="addr-4")


@pytest.mark.asyncio
async def test_minting_again_burns_the_previous_code(db, user_id):
    """A user who clicks "link" three times must not end up with three live
    codes — two of them abandoned on screen and still valid."""
    first = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    second = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)

    assert first.code != second.code

    with pytest.raises(LinkError):
        await redeem_link_code(db, code=first.code, channel=AttentionChannel.MEZON, address="addr-5")

    channel = await redeem_link_code(
        db, code=second.code, channel=AttentionChannel.MEZON, address="addr-5"
    )
    assert channel.verified_at is not None


@pytest.mark.asyncio
async def test_failed_attempts_are_counted(db, user_id):
    """`attempts` is what makes a code being hammered visible at all."""
    row = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    await redeem_link_code(db, code=row.code, channel=AttentionChannel.MEZON, address="addr-6")

    for _ in range(3):
        with pytest.raises(LinkError):
            await redeem_link_code(db, code=row.code, channel=AttentionChannel.MEZON, address="x")

    refreshed = (
        await db.execute(select(ChannelLinkCode).where(ChannelLinkCode.id == row.id))
    ).scalars().one()
    assert refreshed.attempts == 4


@pytest.mark.asyncio
async def test_channel_without_an_adapter_cannot_be_linked(db, user_id):
    with pytest.raises(LinkError):
        await create_link_code(db, user_id, channel=AttentionChannel.SLACK)


@pytest.mark.asyncio
async def test_relinking_the_same_address_reuses_the_row(db, user_id):
    """Re-linking after a bot reinstall must not create a second row, or
    every notification would arrive twice."""
    first_code = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    first = await redeem_link_code(
        db, code=first_code.code, channel=AttentionChannel.MEZON, address="same-addr"
    )

    second_code = await create_link_code(db, user_id, channel=AttentionChannel.MEZON)
    second = await redeem_link_code(
        db, code=second_code.code, channel=AttentionChannel.MEZON, address="same-addr"
    )

    assert first.id == second.id
