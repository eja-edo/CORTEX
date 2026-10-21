"""'Select first, write later' (DESIGN §5.7, N6): rank pending jobs with 0 tokens, keep the top K
per staff member (R5: the cap is per owner_staff_ref, not per sandbox), skip the rest."""
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.db import models as m
from cortex_leads.domain.pack import load_pack
from cortex_leads.sandbox.policy import check_budget
from cortex_leads.skills.registry import TURN_EVENT

UNASSIGNED = "unassigned"


def _rank(job: m.FollowupJob, conv: m.Conversation, priority: list[str]) -> tuple[Any, ...]:
    # a customer waiting now > promised date due > a priority intent of the domain pack (R21) > older silence first
    return (job.event_type != TURN_EVENT, job.event_type != "conversation.promised_date_reached", conv.intent not in priority,
            conv.last_customer_at or datetime.max.replace(tzinfo=UTC))


async def select_jobs(session: AsyncSession, sandbox: m.Sandbox, now: datetime
                      ) -> list[m.FollowupJob]:
    rows = (await session.execute(
        select(m.FollowupJob, m.Conversation)
        .join(m.Conversation, m.Conversation.id == m.FollowupJob.conversation_id)
        .where(m.FollowupJob.sandbox_id == sandbox.id, m.FollowupJob.status == "pending",
               m.FollowupJob.not_before <= now)
        .with_for_update(of=m.FollowupJob, skip_locked=True))).all()
    if not rows:
        return []
    gate = await check_budget(session, sandbox, "runs", now)
    if gate is not None and gate.code == "PAUSED":
        return []  # kill switch: leave the jobs alone
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    owner_col = func.coalesce(m.Conversation.owner_staff_ref, UNASSIGNED)
    used = dict((await session.execute(
        select(owner_col, func.count())
        .select_from(m.Draft).join(m.Conversation, m.Conversation.id == m.Draft.conversation_id)
        .where(m.Draft.sandbox_id == sandbox.id, m.Draft.created_at >= day, m.Draft.status != "shadow",
               or_(m.Draft.run_id.is_(None), m.Draft.run_id.not_in(
                   select(m.TriggerRun.id).where(m.TriggerRun.event_type == TURN_EVENT))))
        .group_by(owner_col))).all())
    cap = sandbox.budget.get("drafts_per_staff_per_day", 0)  # missing cap = deny (as check_budget)
    chosen: list[m.FollowupJob] = []
    priority = load_pack(sandbox).priority_intents
    for job, conv in sorted(rows, key=lambda r: _rank(*r, priority)):
        owner = conv.owner_staff_ref or UNASSIGNED
        if gate is None and job.event_type == TURN_EVENT:  # a customer is waiting: no top-K, still counted in runs/tokens
            chosen.append(job)
            continue
        if gate is None and used.get(owner, 0) < cap:
            used[owner] = used.get(owner, 0) + 1
            chosen.append(job)
            continue
        job.status, job.updated_at = "skipped", now
        session.add(m.DecisionLog(
            tenant_id=job.tenant_id, conversation_id=conv.id, decision="job_skipped_budget",
            reason_code="runs_cap" if gate else "staff_cap", detail={"owner": owner}, at=now))
    await session.flush()
    return chosen
