"""User Preferences (Milestone 6.2) — quiet hours today, read by the
Attention Gate's step 3 (app.services.availability), written through the
`/api/preferences` endpoint. See UserPreferences' docstring in app.models
for the "missing row = no quiet hours configured" contract.

`disabled_reason_keys` (the redesigned 4.5 follow-up to A2) uses the same
contract: no row, or an empty list, means every reason is on.
"""

from datetime import time
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import UserPreferences


async def get_preferences_async(session: AsyncSession, user_id: UUID) -> UserPreferences | None:
    return await session.get(UserPreferences, user_id)


def get_preferences_sync(session: Session, user_id: UUID) -> UserPreferences | None:
    return session.get(UserPreferences, user_id)


async def upsert_quiet_hours_async(
    session: AsyncSession,
    user_id: UUID,
    *,
    quiet_hours_start: time | None,
    quiet_hours_end: time | None,
) -> UserPreferences:
    prefs = await session.get(UserPreferences, user_id)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        session.add(prefs)
    prefs.quiet_hours_start = quiet_hours_start
    prefs.quiet_hours_end = quiet_hours_end
    await session.commit()
    await session.refresh(prefs)
    return prefs


def is_reason_disabled(prefs: UserPreferences | None, reason_key: str) -> bool:
    if prefs is None:
        return False
    return reason_key in (prefs.disabled_reason_keys or [])


async def set_reason_enabled_async(
    session: AsyncSession, user_id: UUID, *, reason_key: str, enabled: bool
) -> None:
    prefs = await session.get(UserPreferences, user_id)
    if prefs is None:
        if enabled:
            # No row already means "on" — nothing to turn back on, so
            # avoid writing a row for a no-op (same reasoning as quiet
            # hours never requiring a write on first read).
            return
        prefs = UserPreferences(user_id=user_id)
        session.add(prefs)

    disabled = list(prefs.disabled_reason_keys or [])
    if enabled:
        disabled = [r for r in disabled if r != reason_key]
    elif reason_key not in disabled:
        disabled.append(reason_key)
    prefs.disabled_reason_keys = disabled

    await session.commit()
