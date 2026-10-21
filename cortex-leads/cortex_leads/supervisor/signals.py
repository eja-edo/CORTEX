"""AI tổng, the part that needs no model (DESIGN §5.6, §5.7 `condition`): named predicates over the
metadata views, read as `cl_supervisor` (column grants, no free text). A predicate that fires writes a
`proposal`; it never changes anything itself. Thresholds are constants, n < MIN_N never fires."""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import supervisor_session
from cortex_leads.notify import service as notify

MIN_N = 5
WINDOW = timedelta(days=7)
BLOCK_SHARE = 0.30  # runs whose draft the validator stopped
SKIP_SHARE = 0.60  # drafts staff threw away
OUTBOX_BAD_SHARE = 0.30  # sends the bridge refused or that failed
ERROR_STREAK = 3

MAX_CARDS = 3  # DESIGN §5.7 "thẻ chiến lược": at most three open at once, default none
AFTER_STEP_H, AFTER_MAX_H = 4, 72

LABELS = {"blocked_spike": "tỷ lệ nháp bị chặn cao", "error_streak": "lỗi liên tiếp",
          "skipped_high": "nhân viên bỏ nhiều nháp", "outbox_failing": "gửi tin hay thất bại"}


@dataclass
class Finding:
    signal: str
    sandbox_id: UUID
    kind: str  # rollback_skill | pause_sandbox | review_skill
    target: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, Any] = field(default_factory=dict)


async def read_findings(tenant_id: UUID, now: datetime) -> list[Finding]:
    """Everything here comes through supervisor_session: a text column raises, it is not filtered."""
    since, found = now - WINDOW, []
    p = {"since": since}
    async with supervisor_session(tenant_id) as s:
        per_skill = (await s.execute(text(
            "select sandbox_id, skill_name, skill_version, count(*) as n, "
            "count(*) filter (where cardinality(blocked_codes) > 0) as blocked, "
            "count(*) filter (where staff_outcome is not null) as decided, "
            "count(*) filter (where staff_outcome = 'skipped') as skipped "
            "from supervisor_run_view where started_at >= :since group by 1, 2, 3"), p)).all()
        for sb, skill, ver, n, blocked, decided, skipped in per_skill:
            tgt = {"skill": skill, "version": ver}
            if n >= MIN_N and blocked / n >= BLOCK_SHARE:
                code = (await s.execute(text(
                    "select c from supervisor_run_view, unnest(blocked_codes) c where sandbox_id = :sb and "
                    "skill_name = :sk and started_at >= :since group by 1 order by count(*) desc, 1 limit 1"),
                    {**p, "sb": sb, "sk": skill})).scalar()
                found.append(Finding("blocked_spike", sb, "rollback_skill", tgt,
                                     {"runs": n, "blocked": blocked, "top_code": code}))
            if decided >= MIN_N and skipped / decided >= SKIP_SHARE:
                found.append(Finding("skipped_high", sb, "review_skill", tgt, {"decided": decided, "skipped": skipped}))
        for sb, skill in (await s.execute(text(
                "select distinct sandbox_id, skill_name from supervisor_run_view where started_at >= :since"), p)).all():
            last = (await s.execute(text(
                "select status from supervisor_run_view where sandbox_id = :sb and skill_name = :sk "
                "order by started_at desc limit :k"), {"sb": sb, "sk": skill, "k": ERROR_STREAK})).scalars().all()
            if len(last) == ERROR_STREAK and all(x == "error" for x in last):
                found.append(Finding("error_streak", sb, "pause_sandbox", {"skill": skill}, {"consecutive_errors": ERROR_STREAK}))
        out = (await s.execute(text(
            "select count(*), count(*) filter (where status in ('refused', 'error')) "
            "from supervisor_outbox_view where created_at >= :since"), p)).one()
    if out[0] >= MIN_N and out[1] / out[0] >= OUTBOX_BAD_SHARE:
        found.append(Finding("outbox_failing", UUID(int=0), "pause_sandbox", {}, {"sends": out[0], "failed": out[1]}))
    return found


def _hours(after: str | None) -> int | None:
    return int(after[:-1]) if after and after.endswith("h") and after[:-1].isdigit() else None


async def _card(session: AsyncSession, sandbox_id: UUID, target: dict[str, Any], kind: str, tenant_id: UUID
                ) -> tuple[str, dict[str, Any]]:
    """Turn "staff skip most drafts" into a strategy card: one named field of the live skill and its new value,
    never prose. Falls back to a plain review when there is nothing safe to change, or three cards are open."""
    live = (await session.execute(select(m.SkillVersion).where(
        m.SkillVersion.sandbox_id == sandbox_id, m.SkillVersion.name == target.get("skill"),
        m.SkillVersion.status == "live"))).scalar_one_or_none()
    open_cards = (await session.execute(select(func.count()).select_from(m.Proposal).where(
        m.Proposal.tenant_id == tenant_id, m.Proposal.status == "pending", m.Proposal.kind == "tune_skill"))).scalar_one()
    if live is None or open_cards >= MAX_CARDS:
        return kind, target
    touches, after = (live.manifest.get("limits") or {}).get("max_touches"), _hours((live.manifest.get("trigger") or {}).get("after"))
    if isinstance(touches, int) and 2 <= touches <= 3:  # the range a card is allowed to move within
        change = {"field": "limits.max_touches", "from": touches, "to": touches - 1}
    elif after is not None and after + AFTER_STEP_H <= AFTER_MAX_H:
        change = {"field": "trigger.after", "from": f"{after}h", "to": f"{after + AFTER_STEP_H}h"}
    else:
        return kind, target
    return "tune_skill", {**target, "version": live.version, "change": change}


async def record(session: AsyncSession, tenant_id: UUID, findings: list[Finding], now: datetime) -> int:
    """Open one proposal per finding (idempotent); proposals whose condition cleared become `stale`."""
    care = (await session.execute(select(m.Sandbox.id).where(m.Sandbox.purpose == "customer_care")
                                  .order_by(m.Sandbox.created_at).limit(1))).scalar()
    new, live = 0, set()
    for f in findings:
        sandbox_id = care if f.sandbox_id.int == 0 else f.sandbox_id  # outbox rows carry no sandbox: the care one
        if sandbox_id is None:
            continue
        kind, target = f.kind, f.target
        if kind == "rollback_skill":  # a rollback needs an older version to go back to
            older = (await session.execute(select(m.SkillVersion.id).where(
                m.SkillVersion.sandbox_id == sandbox_id, m.SkillVersion.name == target["skill"],
                m.SkillVersion.status == "retired", m.SkillVersion.version < target["version"]).limit(1))).scalar()
            kind = kind if older else "review_skill"
        if f.signal == "skipped_high":  # staff throw most drafts away: try a gentler version, as a card (a structured change)
            kind, target = await _card(session, sandbox_id, target, kind, tenant_id)
        live.add((sandbox_id, f.signal, target.get("skill", "")))
        pid = (await session.execute(insert(m.Proposal).values(
            id=uuid7(), tenant_id=tenant_id, sandbox_id=sandbox_id, kind=kind, signal=f.signal, target=target,
            evidence=f.evidence, created_at=now).on_conflict_do_nothing().returning(m.Proposal.id))).scalar()
        if pid:
            new += 1
            await notify.enqueue(session, tenant_id, "proposal", pid, now)
    for p in (await session.execute(select(m.Proposal).where(m.Proposal.status == "pending"))).scalars():
        if (p.sandbox_id, p.signal, (p.target or {}).get("skill", "")) not in live:
            p.status, p.decided_by, p.decided_at = "stale", "system:supervisor", now
    return new
