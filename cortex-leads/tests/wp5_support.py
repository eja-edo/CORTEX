"""Shared WP5 test world: tenant + sandbox + messenger conversation + the two shipped skills live."""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.providers import FakeProvider
from cortex_leads.llm.types import LLMResult
from cortex_leads.runner.customer_run import run_job
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.registry import promote
from cortex_leads.tools.registry import default_registry
from cortex_leads.triggers.engine import on_conversation_event

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
SKILLS = Path(__file__).resolve().parents[1] / "sandboxes" / "customer_care" / "skills"
REG = default_registry(clock=lambda: NOW)


@dataclass
class World:
    t: m.Tenant
    sb: m.Sandbox
    cn: m.Connector
    conv: m.Conversation


async def live_skills(t: m.Tenant, sb: m.Sandbox) -> None:
    async with tenant_session(t.id) as s:
        await sync_dir(s, t.id, sb.id, SKILLS)
        for name in ("hoi-lai-khach-im", "hoi-lai-dung-hen"):
            await promote(s, sb.id, name, 3, "shadow")
            await promote(s, sb.id, name, 3, "live")


@pytest.fixture
async def world(tenant_factory, sandbox_factory, connector_factory, conversation_factory,
                message_factory, catalog_factory) -> World:
    t = await tenant_factory()
    sb = await sandbox_factory(t)
    cn = await connector_factory(sb)
    # 26h of silence: just past the free 24h window, so basis == human_agent (R6).
    conv = await conversation_factory(
        cn, display_name="Nguyễn Văn An", intent="hoi_gia", last_customer_at=NOW - timedelta(hours=26),
        last_customer_msg_id="m1", next_check_at=NOW - timedelta(hours=2))
    await message_factory(conv, "Chào shop, em là An, sđt 0901 234 567. Khóa IELTS giá bao nhiêu?",
                          occurred_at=NOW - timedelta(hours=26))
    await catalog_factory(t, code="KH01", name="Khóa IELTS", price=2_500_000)
    await live_skills(t, sb)
    return World(t, sb, cn, conv)


async def set_conv(w: World, **kw) -> None:
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Conversation).where(m.Conversation.id == w.conv.id).values(**kw))


def gateway(*script) -> tuple[LLMGateway, FakeProvider]:
    prov = FakeProvider(list(script))
    return LLMGateway(prov, retry_delay_s=0), prov


def reply(obj, tin: int = 100, tout: int = 20) -> LLMResult:
    return LLMResult(content=obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False),
                     tokens_in=tin, tokens_out=tout, model="fake")


GOOD_DRAFT = {"act": "draft", "reason_code": "khong_ro", "has_new_info": True,
              "claims": [{"value": 2_500_000, "source_id": "KH01"}],
              "text": "Chào chị, khóa IELTS bên em giá 2.500.000đ, chị cần em tư vấn thêm không ạ?"}


async def make_job(w: World, event: str = "conversation.silent") -> m.FollowupJob:
    async with tenant_session(w.t.id) as s:
        conv = await s.get(m.Conversation, w.conv.id)
        jobs = await on_conversation_event(s, conv, event, NOW)
        assert jobs, "engine created no job"
        return jobs[0]


async def run_one(w: World, gw: LLMGateway, job: m.FollowupJob | None = None,
                  now: datetime = NOW) -> m.TriggerRun:
    job = job or await make_job(w)
    async with tenant_session(w.t.id) as s:
        j = await s.get(m.FollowupJob, job.id)
        return await run_job(s, j, gw, REG, now)


async def rows(w: World, model):
    async with tenant_session(w.t.id) as s:
        return list((await s.execute(select(model))).scalars())
