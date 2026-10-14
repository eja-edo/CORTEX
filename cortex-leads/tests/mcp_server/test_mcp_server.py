import json
from datetime import UTC, datetime, timedelta

import pytest

from cortex_leads.db import models as m
from cortex_leads.mcp_server.server import ReadOnlyHandlers, build_server

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)
PII = "SĐT 0912345678 mail an@example.com"


@pytest.fixture
async def world(tenant_factory, sandbox_factory, connector_factory, conversation_factory,
                message_factory, catalog_factory, seed):
    t = await tenant_factory()
    sb = await sandbox_factory(t)
    conn = await connector_factory(sb)
    conv = await conversation_factory(conn, display_name="Nguyễn Văn An",
                                      last_customer_at=NOW - timedelta(hours=30))
    await message_factory(conv, f"Giá bao nhiêu? {PII}")
    await catalog_factory(t, code="KH01")
    await seed(m.Draft(tenant_id=t.id, sandbox_id=sb.id, conversation_id=conv.id,
                       text="Chào anh An, gọi 0987654321 nhé", reason_code="khong_ro"))
    return t, sb, conv


def handlers(t, sb) -> ReadOnlyHandlers:
    return ReadOnlyHandlers(t.id, sb.id, clock=lambda: NOW)


async def test_only_read_tools_exposed(world) -> None:
    t, sb, _ = world
    names = {tool.name for tool in await build_server(handlers(t, sb)).list_tools()}
    assert names == {"list_dropped_leads", "read_conversation", "lookup_catalog", "list_drafts"}
    assert not any("draft_followup" in n or "send" in n for n in names)


async def test_draft_followup_is_unreachable(world) -> None:
    t, sb, conv = world
    h = handlers(t, sb)
    res = await h._call("draft_followup", {"text": "x", "reason_code": "khong_ro",
                                           "has_new_info": True}, conv.id)
    assert res["status"] == "blocked"
    assert res["violations"][0]["code"] == "NOT_ALLOWED"
    assert not hasattr(h, "draft_followup")


async def test_read_conversation_is_redacted(world) -> None:
    t, sb, conv = world
    out = await handlers(t, sb).read_conversation(str(conv.id))
    blob = json.dumps(out, ensure_ascii=False)
    assert out["status"] == "ok"
    assert "0912345678" not in blob and "an@example.com" not in blob
    assert "[PHONE_1]" in blob and "[EMAIL_1]" in blob


async def test_list_drafts_redacted_and_bad_id(world) -> None:
    t, sb, conv = world
    h = handlers(t, sb)
    out = await h.list_drafts()
    blob = json.dumps(out, ensure_ascii=False)
    assert len(out["data"]["drafts"]) == 1
    assert "0987654321" not in blob and "[PHONE_1]" in blob and "An" not in out["data"]["drafts"][0]["text"].split("[")[0]
    assert (await h.read_conversation("not-a-uuid"))["status"] == "error"


async def test_dropped_leads_and_catalog(world) -> None:
    t, sb, conv = world
    h = handlers(t, sb)
    leads = (await h.list_dropped_leads())["data"]["leads"]
    assert [x["conversation_id"] for x in leads] == [str(conv.id)]
    assert (await h.lookup_catalog("KH01"))["data"]["items"][0]["code"] == "KH01"


async def test_other_tenant_sees_nothing(world, tenant_factory, sandbox_factory) -> None:
    _, _, conv = world
    t2 = await tenant_factory(name="Other")
    sb2 = await sandbox_factory(t2)
    h = handlers(t2, sb2)
    assert (await h.read_conversation(str(conv.id)))["status"] == "not_found"
    assert (await h.list_drafts())["data"]["drafts"] == []
    assert (await h.list_dropped_leads())["data"]["leads"] == []
    assert (await h.lookup_catalog("KH01"))["status"] == "not_found"
