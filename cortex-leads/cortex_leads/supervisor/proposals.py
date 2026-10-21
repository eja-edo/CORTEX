"""Acting on a proposal (DESIGN §5.6: the AI proposes, a person confirms). Only the staff UI calls this,
with an owner's identity; the supervisor code path has no import of it."""
import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.errors import CortexError
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack
from cortex_leads.skills.loader import lint
from cortex_leads.skills.manifest import SkillManifest, parse_duration
from cortex_leads.skills.profile import load_profile
from cortex_leads.skills.registry import SkillError, promote, rollback

# What a card may change, and the range it may change to. A field not here cannot be touched by a card.
CHANGEABLE = {"limits.max_touches": (int, 1, 3), "trigger.after": (str, 4, 72)}


async def _apply_card(session: AsyncSession, p: m.Proposal) -> bool:
    """A strategy card: copy the live skill with ONE field changed, as a new version, and put it on trial. The
    live version keeps running; nothing the card does reaches a customer before a person turns the new one on."""
    change, name = (p.target or {}).get("change") or {}, (p.target or {}).get("skill")
    spec = CHANGEABLE.get(change.get("field"))
    base = (await session.execute(select(m.SkillVersion).where(
        m.SkillVersion.sandbox_id == p.sandbox_id, m.SkillVersion.name == name,
        m.SkillVersion.version == (p.target or {}).get("version"), m.SkillVersion.status == "live"))).scalar_one_or_none()
    if spec is None or base is None:  # the skill moved on since the card was made
        return False
    new = change.get("to")
    if spec[0] is int and not (isinstance(new, int) and spec[1] <= new <= spec[2]):
        return False
    if spec[0] is str:
        try:
            ok = isinstance(new, str) and new.endswith("h") and spec[1] <= parse_duration(new).total_seconds() / 3600 <= spec[2]
        except ValueError:
            ok = False
        if not ok:
            return False
    top = (await session.execute(select(func.max(m.SkillVersion.version)).where(
        m.SkillVersion.sandbox_id == p.sandbox_id, m.SkillVersion.name == name))).scalar_one()
    manifest = {**base.manifest, "version": top + 1, "status": "draft"}
    section, key = change["field"].split(".")
    manifest[section] = {**manifest.get(section, {}), key: new}
    parsed = SkillManifest(**manifest)
    sandbox = await session.get(m.Sandbox, p.sandbox_id)
    if lint(parsed, load_profile(sandbox.profile_ref), load_pack(sandbox)):
        return False
    row = m.SkillVersion(tenant_id=p.tenant_id, sandbox_id=p.sandbox_id, name=name, version=top + 1, status="draft",
                         body=base.body, manifest=parsed.model_dump(mode="json"),
                         checksum=hashlib.sha256((parsed.model_dump_json() + base.body).encode()).hexdigest())
    session.add(row)
    await session.flush()
    await promote(session, p.sandbox_id, name, row.version, "shadow")
    return True



async def decide(session: AsyncSession, proposal_id: UUID, *, accept: bool, by: str, now: datetime) -> str:
    """Returns the final status: accepted | dismissed | stale (the thing it pointed at has changed)."""
    p = await session.get(m.Proposal, proposal_id, with_for_update=True)
    if p is None:
        raise CortexError("proposal not found")
    if p.status != "pending":
        return p.status
    status = "accepted" if accept else "dismissed"
    if accept and p.kind == "pause_sandbox":
        sb = await session.get(m.Sandbox, p.sandbox_id)
        sb.status = "paused"  # the kill switch
    elif accept and p.kind == "tune_skill":
        if not await _apply_card(session, p):
            status = "stale"
    elif accept and p.kind == "rollback_skill":
        try:
            await rollback(session, p.sandbox_id, p.target["skill"])
        except SkillError:
            status = "stale"
    p.status, p.decided_by, p.decided_at = status, by, now
    session.add(m.ActionLog(tenant_id=p.tenant_id, action_id=uuid7(), actor=by, tool=f"proposal.{p.kind}",
                            args_masked={"signal": p.signal, "skill": (p.target or {}).get("skill")},
                            status=status, evidence={"proposal_id": str(p.id)}))
    return status
