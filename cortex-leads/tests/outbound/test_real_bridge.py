"""WP8: the core talks to the real Messenger bridge (ASGI, Graph API mocked) - header names, signature
and refusal codes must match on both sides. Real clock: the bridge checks timestamp skew itself."""
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from ob_support import SECRET, configure, run, send, sql
from wp5_support import rows

from bridges.messenger.app import Settings, create_app
from cortex_leads.channels.policy import window_state
from cortex_leads.db import models as m
from cortex_leads.outbound.action_format import build_action, encode
from cortex_leads.outbound.worker import deliver_once


def bridge_for(world, tmp_path, **policy):
    graph: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        graph.append(json.loads(req.content))
        return httpx.Response(200, json={"message_id": f"mid.{len(graph)}"})

    st = Settings(app_secret="a", verify_token="v", page_token="TOKEN", page_id="page1", own_app_id="1",
                  ingest_url="http://x/ingest", connector_id=world.cn.id, connector_secret=SECRET,
                  policy={"ai_send": True, **policy})
    app = create_app(st, http=httpx.AsyncClient(transport=httpx.MockTransport(handler)), data_dir=tmp_path)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bridge"), graph


async def setup(world, owner_engine, **kw):
    now = datetime.now(UTC)
    await configure(world, owner_engine, now=now, **kw)
    await sql(owner_engine, "update sandbox set business_hours = '{\"start\": \"00:00\", \"end\": \"23:59\"}'")
    return now


async def test_auto_message_goes_out_with_disclosure(world, owner_engine, tmp_path):
    now = await setup(world, owner_engine, mode="auto")
    await run(world, now=now)
    client, graph = bridge_for(world, tmp_path)
    assert await deliver_once(datetime.now(UTC), client=client) == 1
    (ob,) = await rows(world, m.Outbox)
    assert ob.status == "sent" and ob.external_message_id == "mid.1"
    (g,) = graph
    assert g["recipient"]["id"] == world.conv.external_id and g["messaging_type"] == "RESPONSE"
    assert g["message"]["text"].endswith("\n— Trợ lý AI của Acme")


async def test_bridge_refuses_ai_when_its_own_policy_says_so(world, owner_engine, tmp_path):
    now = await setup(world, owner_engine, mode="auto")
    await run(world, now=now)
    client, graph = bridge_for(world, tmp_path, ai_send=False)
    await deliver_once(datetime.now(UTC), client=client)
    (ob,) = await rows(world, m.Outbox)
    assert (ob.status, ob.reason) == ("refused", "AI_SEND_DISABLED") and graph == []
    assert len([d for d in await rows(world, m.Draft) if d.status == "proposed"]) == 1


async def test_bridge_refuses_ai_in_human_agent_window_even_if_core_let_it_through(world, owner_engine, tmp_path):
    """Layer 2 on its own: build the action by hand with an ai actor inside the HUMAN_AGENT window."""
    now = await setup(world, owner_engine, mode="manual", silent_h=26)
    await run(world, now=now)
    (d,) = await rows(world, m.Draft)
    await send(world, d, staff="nv1", now=now)
    (ob,) = await rows(world, m.Outbox)
    conv = (await rows(world, m.Conversation))[0]
    cn = (await rows(world, m.Connector))[0]
    w = window_state(conv.channel_kind, conv.last_customer_at, datetime.now(UTC))
    assert w["basis"] == "human_agent"
    client, graph = bridge_for(world, tmp_path)
    for actor, status in (("ai:customer_drafter@1", "refused"), ("staff:nv1", "sent")):
        ob.actor = actor
        body, headers = encode(build_action(ob, conv, cn, w), SECRET.encode(), datetime.now(UTC))
        r = await client.post("/actions", content=body, headers=headers)
        assert r.json()["status"] == status, r.json()
        ob.action_id = UUID(int=int(str(ob.action_id).replace('-', ''), 16) + 1)  # a different action for the second try
    assert r.json()["status"] == "sent" and graph[0]["tag"] == "HUMAN_AGENT"
    assert len(graph) == 1  # the ai attempt never reached Graph


async def test_redelivery_of_the_same_action_does_not_send_twice(world, owner_engine, tmp_path):
    now = await setup(world, owner_engine, mode="auto")
    await run(world, now=now)
    client, graph = bridge_for(world, tmp_path)
    await deliver_once(datetime.now(UTC), client=client)
    await sql(owner_engine, "update outbox set status = 'queued', external_message_id = null")  # crash after POST
    await deliver_once(datetime.now(UTC) + timedelta(seconds=1), client=client)
    assert len(graph) == 1 and (await rows(world, m.Outbox))[0].external_message_id == "mid.1"


async def test_every_message_that_reaches_the_platform_has_an_outbox_row(world, owner_engine, tmp_path):
    """DESIGN A9: no message to the customer without an outbox row (and a draft behind it)."""
    now = await setup(world, owner_engine, mode="auto")
    await run(world, now=now)
    client, graph = bridge_for(world, tmp_path)
    seen: list[str] = []
    real_post = client.post

    async def spy(url, **kw):
        seen.append(json.loads(kw["content"])["action_id"])
        return await real_post(url, **kw)

    client.post = spy  # type: ignore[method-assign]
    await deliver_once(datetime.now(UTC), client=client)
    ids = {str(o.action_id) for o in await rows(world, m.Outbox) if o.draft_id}
    assert seen and set(seen) <= ids and len(graph) == len(seen)
