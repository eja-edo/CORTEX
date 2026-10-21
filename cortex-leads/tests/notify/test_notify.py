"""WP17 (R58): staff push. Content carries no customer data; delivery is idempotent and retried."""
import json
from datetime import timedelta

import httpx
import pytest
from wp5_support import NOW, rows

from cortex_leads.core.ids import uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.notify import service as notify
from cortex_leads.notify import worker


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(worker, "get_settings", lambda: type("S", (), {
        "TELEGRAM_BOT_TOKEN": "123:abc", "PUBLIC_BASE_URL": "https://cx.example.vn/"})())


def telegram(sent: list[dict], status: int = 200) -> httpx.AsyncClient:
    def handler(req: httpx.Request) -> httpx.Response:
        sent.append({"url": str(req.url), **json.loads(req.content)})
        return httpx.Response(status, json={"ok": status == 200})
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def target(world, chat="555") -> None:
    async with tenant_session(world.t.id) as s:
        s.add(m.NotifyTarget(tenant_id=world.t.id, kind="telegram", address=chat))


async def queue(world, kind="handoff", n=1) -> None:
    async with tenant_session(world.t.id) as s:
        for _ in range(n):
            await notify.enqueue(s, world.t.id, kind, uuid7(), NOW)


async def test_groups_by_kind_and_carries_no_customer_data(world):
    await target(world)
    await queue(world, "handoff", 3)
    await queue(world, "booking", 1)
    sent: list[dict] = []
    assert await worker.notify_once(NOW, client=telegram(sent)) == 4
    texts = {x["text"] for x in sent}
    assert texts == {"🔔 3 khách đang chờ nhân viên trả lời.\nMở: https://cx.example.vn/staff",
                     "📅 1 lịch học thử mới.\nMở: https://cx.example.vn/staff"}
    assert all(x["chat_id"] == "555" and "bot123:abc" in x["url"] for x in sent)
    blob = json.dumps(sent, ensure_ascii=False)
    assert "Nguyễn" not in blob and "0901" not in blob  # the world's customer
    assert {r.status for r in await rows(world, m.Notification)} == {"sent"}
    assert await worker.notify_once(NOW, client=telegram(sent)) == 0  # nothing left


async def test_enqueue_is_idempotent(world):
    ref = uuid7()
    async with tenant_session(world.t.id) as s:
        await notify.enqueue(s, world.t.id, "handoff", ref, NOW)
        await notify.enqueue(s, world.t.id, "handoff", ref, NOW)
    assert len(await rows(world, m.Notification)) == 1


async def test_no_target_or_no_token_skips_instead_of_retrying(world, monkeypatch):
    await queue(world)
    sent: list[dict] = []
    await worker.notify_once(NOW, client=telegram(sent))  # no target
    assert not sent and [r.status for r in await rows(world, m.Notification)] == ["skipped"]
    await target(world)
    await queue(world)
    monkeypatch.setattr(worker, "get_settings", lambda: type("S", (), {
        "TELEGRAM_BOT_TOKEN": None, "PUBLIC_BASE_URL": None})())
    await worker.notify_once(NOW, client=telegram(sent))
    assert not sent and {r.status for r in await rows(world, m.Notification)} == {"skipped"}


async def test_failure_backs_off_then_gives_up(world):
    await target(world)
    await queue(world)
    sent: list[dict] = []
    c = telegram(sent, status=500)
    await worker.notify_once(NOW, client=c)
    r = (await rows(world, m.Notification))[0]
    assert (r.status, r.attempts) == ("queued", 1) and r.not_before == NOW + timedelta(seconds=60)
    assert await worker.notify_once(NOW, client=c) == 0  # still backing off
    await worker.notify_once(NOW + timedelta(minutes=2), client=c)
    await worker.notify_once(NOW + timedelta(hours=1), client=c)
    assert (await rows(world, m.Notification))[0].status == "failed"


async def test_tenant_isolation(world, tenant_factory):
    other = await tenant_factory()
    async with tenant_session(other.id) as s:
        s.add(m.NotifyTarget(tenant_id=other.id, kind="telegram", address="999"))
    await queue(world)  # world's tenant has no target of its own
    sent: list[dict] = []
    await worker.notify_once(NOW, client=telegram(sent))
    assert not sent  # the other tenant's chat never receives this tenant's push
