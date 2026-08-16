from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.schemas import ReasonPreference, ReasonPreferenceUpdate, UserPreferencesResponse, UserPreferencesUpdate
from app.services.attention_reason_catalog import REASON_CATALOG
from app.services.feedback_loop import apply_downgrade, dismiss_count_async
from app.services.user_preferences import get_preferences_async, is_reason_disabled, set_reason_enabled_async, upsert_quiet_hours_async

router = APIRouter(prefix="/preferences", tags=["preferences"])


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
