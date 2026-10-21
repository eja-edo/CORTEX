"""Live skill lookup, trigger matching and the draft -> shadow -> live lifecycle."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.db.models import SkillVersion
from cortex_leads.skills.loader import MATCH_FIELDS, SkillError
from cortex_leads.skills.manifest import SkillManifest, parse_duration


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    version: int
    manifest: SkillManifest
    body: str
    checksum: str


async def live_skills_for(session: AsyncSession, sandbox_id: UUID, event_type: str) -> list[LoadedSkill]:
    rows = (await session.execute(select(SkillVersion).where(
        SkillVersion.sandbox_id == sandbox_id, SkillVersion.status == "live",
    ).order_by(SkillVersion.name))).scalars()
    skills = [LoadedSkill(r.name, r.version, SkillManifest(**r.manifest), r.body, r.checksum) for r in rows]
    return [s for s in skills if s.manifest.trigger.on == event_type]


async def shadow_skills_for(session: AsyncSession, sandbox_id: UUID, event_type: str) -> list[LoadedSkill]:
    """Skills on trial (DESIGN §5.8): they see real events, write drafts nobody is shown, send nothing."""
    rows = (await session.execute(select(SkillVersion).where(
        SkillVersion.sandbox_id == sandbox_id, SkillVersion.status == "shadow",
    ).order_by(SkillVersion.name))).scalars()
    skills = [LoadedSkill(r.name, r.version, SkillManifest(**r.manifest), r.body, r.checksum) for r in rows]
    return [s for s in skills if s.manifest.trigger.on == event_type]


DEFAULT_SILENT_AFTER = timedelta(hours=24)


def silent_after(skill: LoadedSkill) -> timedelta:
    return parse_duration(skill.manifest.trigger.after) if skill.manifest.trigger.after else DEFAULT_SILENT_AFTER


async def silent_after_for(session: AsyncSession, sandbox_id: UUID) -> timedelta:
    """DESIGN §5.7: the clock rings at the earliest `after` of the live conversation.silent skills."""
    return min(map(silent_after, await live_skills_for(session, sandbox_id, "conversation.silent")),
               default=DEFAULT_SILENT_AFTER)


TURN_EVENT = "conversation.awaiting_reply"  # WP16: DESIGN §5.7 `turn`
DEFAULT_TURN_AFTER = timedelta(seconds=30)


async def reply_after_for(session: AsyncSession, sandbox_id: UUID) -> timedelta | None:
    """How long a customer must stay quiet before the turn is theirs to answer; None = no live skill."""
    skills = await live_skills_for(session, sandbox_id, TURN_EVENT)
    return min((parse_duration(s.manifest.trigger.after) if s.manifest.trigger.after
                else DEFAULT_TURN_AFTER for s in skills), default=None)


def match(skill: LoadedSkill, conversation: Any) -> bool:
    """Equality only, on allowed conversation fields (DESIGN §5.7). Empty match = always."""
    return all(k in MATCH_FIELDS and getattr(conversation, k, None) == v
               for k, v in skill.manifest.trigger.match.items())


_FORWARD = {"draft": {"shadow"}, "shadow": {"live"}, "retired": {"live"}}  # retired->live = rollback


async def _get(session: AsyncSession, sandbox_id: UUID, name: str, version: int) -> SkillVersion:
    row = (await session.execute(select(SkillVersion).where(
        SkillVersion.sandbox_id == sandbox_id, SkillVersion.name == name,
        SkillVersion.version == version))).scalar_one_or_none()
    if row is None:
        raise SkillError(f"{name}@{version} not found")
    return row


async def promote(session: AsyncSession, sandbox_id: UUID, name: str, version: int,
                  to: Literal["shadow", "live"]) -> SkillVersion:
    row = await _get(session, sandbox_id, name, version)
    if to not in _FORWARD.get(row.status, set()):
        raise SkillError(f"{name}@{version}: cannot go {row.status} -> {to}")
    if to == "live":  # retire the current live first: partial unique allows one per name
        cur = (await session.execute(select(SkillVersion).where(
            SkillVersion.sandbox_id == sandbox_id, SkillVersion.name == name,
            SkillVersion.status == "live"))).scalars().all()
        for c in cur:
            c.status = "retired"
        await session.flush()
    row.status = to
    await session.flush()
    return row


async def rollback(session: AsyncSession, sandbox_id: UUID, name: str) -> SkillVersion:
    """Make the newest retired version below the live one live again."""
    rows = (await session.execute(select(SkillVersion).where(
        SkillVersion.sandbox_id == sandbox_id, SkillVersion.name == name,
    ).order_by(SkillVersion.version.desc()))).scalars().all()
    live = next((r for r in rows if r.status == "live"), None)
    prev = next((r for r in rows if r.status == "retired" and (live is None or r.version < live.version)), None)
    if prev is None:
        raise SkillError(f"{name}: no earlier version to roll back to")
    return await promote(session, sandbox_id, name, prev.version, "live")


async def retire(session: AsyncSession, sandbox_id: UUID, name: str, version: int) -> SkillVersion:
    """Switch a skill off (live or on trial). A retired version can be made live again (rollback)."""
    row = await _get(session, sandbox_id, name, version)
    if row.status not in ("live", "shadow"):
        raise SkillError(f"{name}@{version}: only a live or shadow skill can be switched off, it is {row.status}")
    row.status = "retired"
    await session.flush()
    return row
