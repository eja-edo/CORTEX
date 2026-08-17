from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database_async import get_async_db
from app.dependencies import (
    get_current_active_user,
    get_current_user_or_internal,
    require_internal_service,
)
from app.models import AttentionChannel, UserChannel
from app.schemas import (
    ChannelLinkCodeRequest,
    ChannelLinkCodeResponse,
    ChannelRedeemRequest,
    ChannelResolveResponse,
    ReasonPreference,
    ReasonPreferenceUpdate,
    UserChannelCreate,
    UserChannelResponse,
    UserChannelUpdate,
    UserPreferencesResponse,
    UserPreferencesUpdate,
)
from app.services.attention_reason_catalog import REASON_CATALOG
from app.services.channel_link import LinkError, create_link_code, redeem_link_code
from app.services.delivery.registry import is_registerable, registered_channels
from app.services.feedback_loop import apply_downgrade, dismiss_count_async
from app.services.user_channels import (
    address_hint,
    resolve_channel_async,
    delete_channel_async,
    list_channels_async,
    register_channel_async,
    update_channel_async,
)
from app.services.user_preferences import get_preferences_async, is_reason_disabled, set_reason_enabled_async, upsert_quiet_hours_async

router = APIRouter(prefix="/preferences", tags=["preferences"])


def _to_channel_response(row: UserChannel) -> UserChannelResponse:
    return UserChannelResponse(
        id=row.id,
        channel=row.channel,
        label=row.label,
        address_hint=address_hint(row.address),
        enabled=row.enabled,
        verified=row.verified_at is not None,
        min_level=row.min_level,
        last_used_at=row.last_used_at,
        created_at=row.created_at,
    )


@router.get("", response_model=UserPreferencesResponse)
async def get_preferences(
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Milestone 6.2. No row yet is a normal state, not a 404 — it means
    quiet hours aren't configured, same as an explicit null/null row."""
    prefs = await get_preferences_async(db, current_user.id)
    if prefs is None:
        return UserPreferencesResponse(quiet_hours_start=None, quiet_hours_end=None)
    return prefs


@router.put("", response_model=UserPreferencesResponse)
async def update_preferences(
    payload: UserPreferencesUpdate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Send both fields null to clear quiet hours entirely."""
    return await upsert_quiet_hours_async(
        db, current_user.id,
        quiet_hours_start=payload.quiet_hours_start,
        quiet_hours_end=payload.quiet_hours_end,
    )


@router.get("/reasons", response_model=list[ReasonPreference])
async def list_reason_preferences(
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """The redesigned 4.5 audit list (see A2's section in
    docs/planning-v3.md): every registered reason_key, its baseline
    importance, whether this user has turned it off, and — 6.9 M2 — how
    many times they've dismissed it and what level that's downgraded it
    to (the same computation the Gate applies live)."""
    prefs = await get_preferences_async(db, current_user.id)
    reasons = []
    for reason_key, meta in sorted(REASON_CATALOG.items()):
        dismiss_count = await dismiss_count_async(db, current_user.id, reason_key)
        reasons.append(ReasonPreference(
            reason_key=reason_key,
            description=meta.description,
            base_level=meta.base_level,
            enabled=not is_reason_disabled(prefs, reason_key),
            dismiss_count=dismiss_count,
            effective_level=apply_downgrade(meta.base_level, dismiss_count),
        ))
    return reasons


@router.put("/reasons/{reason_key}", response_model=ReasonPreference)
async def update_reason_preference(
    reason_key: str,
    payload: ReasonPreferenceUpdate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    meta = REASON_CATALOG.get(reason_key)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Unknown reason_key: {reason_key}")

    await set_reason_enabled_async(db, current_user.id, reason_key=reason_key, enabled=payload.enabled)
    dismiss_count = await dismiss_count_async(db, current_user.id, reason_key)
    return ReasonPreference(
        reason_key=reason_key, description=meta.description, base_level=meta.base_level, enabled=payload.enabled,
        dismiss_count=dismiss_count, effective_level=apply_downgrade(meta.base_level, dismiss_count),
    )


# ── Delivery channels (bước 0) ────────────────────────────────────────────
# The reason toggles above answer "what am I told about"; these answer
# "where does it reach me". Both live under /preferences because they are
# the same page to a user, and both follow boundary #2: nothing here needs
# to be switched on for Cortex to work — in-app delivery is implicit and
# has no row.


@router.get("/channels", response_model=list[UserChannelResponse])
async def list_channels(
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    rows = await list_channels_async(db, current_user.id)
    return [_to_channel_response(row) for row in rows]


@router.get("/channels/available", response_model=list[str])
async def list_available_channels():
    """Which channels have a delivery adapter in this build.

    Driven by the registry rather than the enum on purpose: `AttentionChannel`
    declares channels ahead of their adapters (see its docstring), and a
    settings UI offering a channel that cannot deliver would be lying.
    """
    return [c.value for c in registered_channels() if is_registerable(c)]


@router.post("/channels", response_model=UserChannelResponse, status_code=201)
async def register_channel(
    payload: UserChannelCreate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """Register a route. Re-posting the same address updates that row
    instead of adding a duplicate — see `register_channel_async`."""
    try:
        row = await register_channel_async(
            db, current_user.id,
            channel=payload.channel, address=payload.address, label=payload.label,
            config=payload.config, min_level=payload.min_level,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_channel_response(row)


@router.put("/channels/{channel_id}", response_model=UserChannelResponse)
async def update_channel(
    channel_id: UUID,
    payload: UserChannelUpdate,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    row = await update_channel_async(
        db, current_user.id, channel_id,
        enabled=payload.enabled, min_level=payload.min_level, label=payload.label,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Channel not found")
    return _to_channel_response(row)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(
    channel_id: UUID,
    current_user=Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    if not await delete_channel_async(db, current_user.id, channel_id):
        raise HTTPException(status_code=404, detail="Channel not found")


@router.get("/channels/resolve", response_model=ChannelResolveResponse)
async def resolve_channel(
    channel: AttentionChannel,
    address: str,
    _=Depends(require_internal_service),
    db: AsyncSession = Depends(get_async_db),
):
    """Bot-only: map a chat address to the Cortex user it belongs to.

    Service auth with no `X-User-ID`, because this is the call that
    *establishes* which user the caller may act as — accepting one would
    be circular. Returns `linked: false` rather than 404 so the bot can
    tell "not linked yet" (answer with linking instructions) from "backend
    is unreachable" (answer with an apology and retry later).
    """
    row = await resolve_channel_async(db, channel=channel, address=address)
    if row is None:
        return ChannelResolveResponse(linked=False)
    return ChannelResolveResponse(
        linked=True, user_id=row.user_id, channel_id=row.id, enabled=row.enabled
    )


@router.post("/channels/link-code", response_model=ChannelLinkCodeResponse)
async def create_channel_link_code(
    payload: ChannelLinkCodeRequest,
    current_user=Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Mint a one-time code to type into the chat app.

    Deliberately **`get_current_active_user`, not the internal variant**:
    minting is the step that carries the proof of identity, and a service
    key that could mint codes for arbitrary users would hand out the
    ability to attach any chat account to any person.
    """
    try:
        row = await create_link_code(db, current_user.id, channel=payload.channel)
    except LinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ChannelLinkCodeResponse(
        code=row.code,
        channel=row.channel,
        expires_in=settings.CHANNEL_LINK_CODE_TTL_SECONDS,
        instruction=f"*link {row.code}",
    )


@router.post("/channels/redeem", response_model=UserChannelResponse)
async def redeem_channel_link_code(
    payload: ChannelRedeemRequest,
    _=Depends(require_internal_service),
    db: AsyncSession = Depends(get_async_db),
):
    """Bot-only. Exchanges a code for a verified channel.

    Takes no user identity from the caller at all — the code determines
    which account gets linked. That is the point: the bot knows a chat id
    and a code, and only the code proves whose account it is.
    """
    try:
        row = await redeem_link_code(
            db, code=payload.code, channel=payload.channel,
            address=payload.address, label=payload.label,
        )
    except LinkError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _to_channel_response(row)
