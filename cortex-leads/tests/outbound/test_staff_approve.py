"""WP8: "Duyệt & gửi" (review API + staff page), supervisor counts, skill lint, CLI. Real clock: the
HTTP layer takes its own `now`, so conversations are made fresh relative to it."""
import argparse
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from ob_support import Bridge, configure, run, sql
from wp5_support import rows

from cortex_leads import cli
from cortex_leads.db import models as m
from cortex_leads.domain.pack import DomainPack
from cortex_leads.outbound.worker import deliver_once
from cortex_leads.skills.loader import lint
from cortex_leads.skills.manifest import SkillManifest
from cortex_leads.skills.profile import load_profile


def hdr(key):
    return {"X-Api-Key": key}


async def ready(world, owner_engine, api_key_factory, **kw):
    now = datetime.now(UTC)
    await configure(world, owner_engine, now=now, **kw)
    await run(world, now=now)
    (d,) = await rows(world, m.Draft)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    return d, key, now


async def approve(client, d, key, **body):
    return await client.post(f"/review/drafts/{d.id}/action", json={"action": "approved", **body},
                             headers=hdr(key))


async def test_approve_queues_a_staff_message_and_records_the_outcome(app_client, world, owner_engine,
                                                                     api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)
    assert await rows(world, m.Outbox) == []  # manual: nothing until a person clicks
    r = await approve(app_client, d, key)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    (ob,) = await rows(world, m.Outbox)
    assert ob.actor == "staff:nv1" and ob.disclosure is None and ob.status == "queued" and ob.text == d.text
    (row,) = await rows(world, m.Draft)
    assert row.status == "approved" and row.staff_ref == "nv1" and row.decided_at
    (sa,) = await rows(world, m.StaffAction)
    assert sa.action == "approved" and sa.staff_ref == "nv1" and sa.edited_text is None
    assert (await rows(world, m.TriggerRun))[0].staff_outcome == "sent"
    bridge = Bridge(now=datetime.now(UTC))
    assert await deliver_once(datetime.now(UTC), client=bridge.client) == 1
    assert bridge.calls[0]["actor"] == "staff:nv1"
    assert (await rows(world, m.Draft))[0].status == "sent"


async def test_approve_with_edited_text_sends_the_edit(app_client, world, owner_engine, api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)
    r = await approve(app_client, d, key, edited_text="Chào chị, em nhắn lại ạ")
    assert r.status_code == 200
    (ob,) = await rows(world, m.Outbox)
    assert ob.text == "Chào chị, em nhắn lại ạ"
    assert (await rows(world, m.StaffAction))[0].edited_text == "Chào chị, em nhắn lại ạ"
    assert (await rows(world, m.TriggerRun))[0].staff_outcome == "edited"


async def test_approve_twice_sends_once(app_client, world, owner_engine, api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)
    assert (await approve(app_client, d, key)).status_code == 200
    r = await approve(app_client, d, key)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_PROPOSED"
    assert len(await rows(world, m.Outbox)) == 1 and len(await rows(world, m.StaffAction)) == 1


async def test_without_outbound_the_old_behaviour_stays(app_client, world, owner_engine, api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)
    await sql(owner_engine, "update connector set outbound = null")
    r = await approve(app_client, d, key)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "OUTBOUND_OFF"
    assert await rows(world, m.Outbox) == [] and await rows(world, m.StaffAction) == []
    assert (await rows(world, m.Draft))[0].status == "proposed"
    assert [x.reason_code for x in await rows(world, m.DecisionLog) if x.decision == "send_refused_at_approval"] \
        == ["OUTBOUND_OFF"]  # the refusal is logged even though the request failed
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "sent"}, headers=hdr(key))
    assert r.status_code == 200 and (await rows(world, m.Draft))[0].status == "sent"  # "I sent it myself"


async def test_approve_after_the_window_closed_is_refused(app_client, world, owner_engine, api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)
    await sql(owner_engine, "update conversation set last_customer_at = now() - interval '9 days'")
    await sql(owner_engine, "update message set occurred_at = now() - interval '9 days'")
    r = await approve(app_client, d, key)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "WINDOW_CLOSED"
    assert await rows(world, m.Outbox) == []


async def test_staff_page_offers_the_button_only_when_outbound_is_on(app_client, world, owner_engine,
                                                                    api_key_factory):
    d, key, _ = await ready(world, owner_engine, api_key_factory)

    async def login():
        form = await app_client.get("/staff/login")
        token = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
        await app_client.post("/staff/login", data={"api_key": key, "csrf": token})

    await login()
    page = await app_client.get("/staff")
    assert 'value="approved"' in page.text and "Duyệt &amp; gửi" in page.text
    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
    r = await app_client.post(f"/staff/draft/{d.id}", data={"action": "approved", "csrf": csrf,
                                                            "edited_text": d.text})
    assert r.status_code == 303 and r.headers["location"] == "/staff?msg=ok"
    (ob,) = await rows(world, m.Outbox)
    assert ob.text == d.text and (await rows(world, m.StaffAction))[0].edited_text is None  # unchanged = no edit


async def test_staff_page_hides_the_button_without_outbound(app_client, world, owner_engine, api_key_factory):
    _, key, _ = await ready(world, owner_engine, api_key_factory, outbound=False)
    form = await app_client.get("/staff/login")
    token = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
    await app_client.post("/staff/login", data={"api_key": key, "csrf": token})
    page = await app_client.get("/staff")
    assert 'value="approved"' not in page.text and 'value="sent"' in page.text


# --- supervisor ---------------------------------------------------------------------------------------
async def test_supervisor_counts_outbox_without_text(app_client, world, api_key_factory, seed):
    for i in range(6):
        await seed(m.Outbox(tenant_id=world.t.id, action_id=uuid4(), conversation_id=world.conv.id,
                            connector_id=world.cn.id,
            actor="ai:customer_drafter@1", text="Bí mật 0901234567", status="sent"))
    await seed(m.Outbox(tenant_id=world.t.id, action_id=uuid4(), conversation_id=world.conv.id,
                        connector_id=world.cn.id, actor="staff:nv1", text="Bí mật", status="refused",
                        reason="WINDOW_CLOSED"))
    _, key = await api_key_factory(world.t, "supervisor", None)
    r = await app_client.get("/supervisor/summary?since=2020-01-01T00:00:00", headers=hdr(key))
    ob = r.json()["outbox"]
    assert ob["status"] == {"sent": 6, "refused": None} and ob["actor_kind"] == {"ai": 6, "staff": None}
    assert ob["reason"] == {"WINDOW_CLOSED": None}
    assert "Bí mật" not in r.text and "nv1" not in r.text


# --- skill lint and CLI ---------------------------------------------------------------------------------
def manifest(**kw):
    base = {"name": "x", "description": "d", "version": 1,
            "trigger": {"kind": "relative", "on": "conversation.silent"},
            "requires_tools": ["read_messages", "draft_followup"], "output_kind": "draft_for_staff"}
    return SkillManifest(**{**base, **kw})


@pytest.mark.parametrize("kw,expect", [
    ({"send_policy": {"mode": "auto"}}, "requires tool send_message"),
    ({"send_policy": {"mode": "auto"}, "requires_tools": ["send_message"]}, "requires output_kind"),
    ({"output_kind": "send_to_customer"}, "requires tool send_message"),
    ({"send_policy": {"mode": "manual", "auto_when": {"quiet": 1}}}, "auto_when keys"),
    ({"send_policy": {"mode": "manual", "auto_when": {"window": "human_agent"}}}, "window may only"),
])
def test_lint_send_policy(kw, expect):
    errs = lint(manifest(**kw), load_profile("customer_drafter@1"), DomainPack())
    assert any(expect in e for e in errs), errs


def test_lint_accepts_a_proper_auto_skill():
    ok = manifest(send_policy={"mode": "auto", "auto_when": {"window": "free", "max_per_contact_per_day": 1}},
                  requires_tools=["read_messages", "draft_followup", "send_message"],
                  output_kind="send_to_customer")
    assert lint(ok, load_profile("customer_drafter@1"), DomainPack()) == []


async def test_cli_set_send_mode_promote_and_deliver(world, owner_engine, capsys):
    ns = argparse.Namespace(tenant=world.t.id, sandbox=world.sb.id)
    await cli.cmd_set_send_mode(argparse.Namespace(**vars(ns), mode="auto"))
    assert (await rows(world, m.Sandbox))[0].send_mode == "auto"
    assert [a.tool for a in await rows(world, m.ActionLog)] == ["cli.set_send_mode"]
    await cli.cmd_promote_skill(argparse.Namespace(**vars(ns), name="thu-nhanh", version=1, to="shadow"))
    assert "thu-nhanh@1 shadow" in capsys.readouterr().out
    await cli.cmd_deliver_outbox(argparse.Namespace())
    assert "delivered=0" in capsys.readouterr().out
