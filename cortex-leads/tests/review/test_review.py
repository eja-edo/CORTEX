from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


def hdr(key):
    return {"X-Api-Key": key}


async def make_draft(w, seed, status="proposed", with_run=True):
    old = datetime.now(UTC) - timedelta(days=30)  # the world's frozen clock is ahead of real time
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Message).values(occurred_at=old))
        await s.execute(update(m.Conversation).values(last_customer_at=old))
    run = None
    if with_run:
        run = await seed(m.TriggerRun(
            tenant_id=w.t.id, sandbox_id=w.sb.id, skill_name="hoi-lai-khach-im", skill_version=1,
            profile="customer_drafter", profile_version=1, event_type="conversation.silent", status="ok",
            act="draft"))
    return await seed(m.Draft(tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=w.conv.id,
                              run_id=run.id if run else None, status=status, text="Chào chị, em hỏi lại ạ",
                              claims=[], reason_code="khong_ro"))


async def test_auth_required(app_client, world, api_key_factory):
    assert (await app_client.get("/review/drafts")).status_code == 401
    assert (await app_client.get("/review/drafts", headers=hdr("nope"))).status_code == 401
    _, sup = await api_key_factory(world.t, "supervisor", None)
    assert (await app_client.get("/review/drafts", headers=hdr(sup))).status_code == 403


async def test_list_shows_text_window_and_is_audited(app_client, world, api_key_factory, seed):
    await make_draft(world, seed)
    _, key = await api_key_factory(world.t)
    r = await app_client.get("/review/drafts?status=proposed", headers=hdr(key))
    (d,) = r.json()["drafts"]
    assert d["text"].startswith("Chào chị") and d["window"]["open"] is False  
    assert any(a.tool == "review.list_drafts" for a in await rows(world, m.ActionLog))


async def test_sent_records_staff_action_and_run_outcome(app_client, world, api_key_factory, seed):
    d = await make_draft(world, seed)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "sent"}, headers=hdr(key))
    assert r.status_code == 200
    (row,) = await rows(world, m.Draft)
    assert row.status == "sent" and row.staff_ref == "nv1" and row.decided_at
    (sa,) = await rows(world, m.StaffAction)
    assert sa.action == "sent" and sa.staff_ref == "nv1"
    assert (await rows(world, m.TriggerRun))[0].staff_outcome == "sent"
    # second decision on the same draft
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "skipped"}, headers=hdr(key))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_PROPOSED"


async def test_edited_needs_text_and_keeps_it(app_client, world, api_key_factory, seed):
    d = await make_draft(world, seed)
    _, key = await api_key_factory(world.t)
    url = f"/review/drafts/{d.id}/action"
    assert (await app_client.post(url, json={"action": "edited"}, headers=hdr(key))).status_code == 422
    r = await app_client.post(url, json={"action": "edited", "edited_text": "Bản sửa"}, headers=hdr(key))
    assert r.status_code == 200
    assert (await rows(world, m.StaffAction))[0].edited_text == "Bản sửa"
    assert (await rows(world, m.TriggerRun))[0].staff_outcome == "edited"


async def test_self_and_skipped_are_accepted(app_client, world, api_key_factory, seed):
    _, key = await api_key_factory(world.t)
    for act in ("self", "skipped"):
        d = await make_draft(world, seed)
        r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": act}, headers=hdr(key))
        assert r.status_code == 200 and r.json()["status"] == act


async def test_stale_when_customer_wrote_after_draft(app_client, world, api_key_factory, seed,
                                                     message_factory):
    d = await make_draft(world, seed)
    await message_factory(world.conv, "Mình quyết định rồi",
                          occurred_at=datetime.now(UTC) + timedelta(minutes=5))
    _, key = await api_key_factory(world.t)
    for act in ("sent", "edited"):
        r = await app_client.post(f"/review/drafts/{d.id}/action",
                                  json={"action": act, "edited_text": "x"}, headers=hdr(key))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE"
    assert (await rows(world, m.Draft))[0].status == "proposed"
    # not sending anything is still fine
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "skipped"}, headers=hdr(key))
    assert r.status_code == 200


async def test_expired_draft_is_stale(app_client, world, api_key_factory, seed):
    d = await make_draft(world, seed, status="expired")
    _, key = await api_key_factory(world.t)
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "sent"}, headers=hdr(key))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "STALE"


async def test_rls_other_tenant_key_sees_nothing(app_client, world, api_key_factory, seed,
                                                 tenant_factory):
    d = await make_draft(world, seed)
    other = await tenant_factory("B")
    _, key_b = await api_key_factory(other)
    assert (await app_client.get("/review/drafts", headers=hdr(key_b))).json()["drafts"] == []
    r = await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "sent"}, headers=hdr(key_b))
    assert r.status_code == 404
    assert (await rows(world, m.Draft))[0].status == "proposed"


async def test_touch_counts_only_when_staff_sends(app_client, world, api_key_factory, seed):  # R36
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    touches = lambda: _touches(world)  # noqa: E731
    for act, text, want in (("skipped", None, 0), ("self", None, 0), ("sent", None, 1), ("edited", "Chào chị ạ", 2)):
        d = await make_draft(world, seed)
        r = await app_client.post(f"/review/drafts/{d.id}/action",
                                  json={"action": act, "edited_text": text}, headers=hdr(key))
        assert r.status_code == 200 and await touches() == want, act
        await app_client.post(f"/review/drafts/{d.id}/action", json={"action": "sent"}, headers=hdr(key))
        assert await touches() == want  # a repeat decision is a 409 and spends nothing


async def _touches(world):
    return (await rows(world, m.Conversation))[0].touches
