"""The record every model-backed job leaves (WP33): one `trigger_run` row, so the tokens count against the sandbox's budget and the
supervisor sees that a run happened, and the RunContext the gateway needs (tenant and actor from the server, never from a prompt)."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.skills.profile import AgentProfile
from cortex_leads.skills.registry import LoadedSkill


def start_run(session: AsyncSession, sandbox: m.Sandbox, profile: AgentProfile, skill: LoadedSkill, *, event_type: str, job: str,
              now: datetime) -> tuple[m.TriggerRun, RunContext]:
    run = m.TriggerRun(id=uuid7(), tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id, skill_name=skill.name,
                       skill_version=skill.version, profile=profile.id, profile_version=profile.version, event_type=event_type,
                       status="ok", blocked_codes=[], tokens_in=0, tokens_out=0, started_at=now)
    session.add(run)
    ctx = RunContext(run_id=run.id, tenant_id=sandbox.tenant_id, sandbox_id=sandbox.id, profile=profile.id,
                     profile_version=profile.version, principal=SystemPrincipal(job=job), scope=Scope())
    return run, ctx
