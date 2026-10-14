"""WP13: staff review page. Login, CSRF, RLS, reuse of review.api's decision logic."""
import re
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from wp5_support import rows

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session


async def make_draft(w, seed, text="Chào chị, em hỏi lại ạ", age_days=30):
    old = datetime.now(UTC) - timedelta(days=age_days)
    async with tenant_session(w.t.id) as s:
        await s.execute(update(m.Message).values(occurred_at=old))
        await s.execute(update(m.Conversation).values(last_customer_at=old))
    return await seed(m.Draft(tenant_id=w.t.id, sandbox_id=w.sb.id, conversation_id=w.conv.id, status="proposed",
                              text=text, claims=[], reason_code="so_sanh"))


async def login(client, key):
    form = await client.get("/staff/login")
    csrf = re.search(r'name="csrf" value="([^"]+)"', form.text).group(1)
    return await client.post("/staff/login", data={"api_key": key, "csrf": csrf})


def csrf_of(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


async def test_anonymous_is_sent_to_login(app_client, world):
    for path in ("/staff", f"/staff/c/{world.conv.id}"):
        r = await app_client.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/staff/login"
    assert "Đăng nhập" in (await app_client.get("/staff/login")).text


async def test_wrong_key_and_wrong_role_rejected(app_client, world, api_key_factory):
    assert (await login(app_client, "nope")).headers["location"].startswith("/staff/login")
    _, sup = await api_key_factory(world.t, "supervisor", None)
    assert (await login(app_client, sup)).headers["location"].startswith("/staff/login")
    assert (await app_client.get("/staff")).status_code == 303


async def test_login_needs_csrf_and_cookie_flags(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t)
    assert (await app_client.post("/staff/login", data={"api_key": key, "csrf": "x"})).status_code == 403
    r = await login(app_client, key)
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 303 and "httponly" in cookie and "samesite=strict" in cookie
    assert key not in r.headers["set-cookie"]  # the key itself never goes in the cookie
    page = await app_client.get("/staff")
    assert page.status_code == 200 and "Hàng chờ" in page.text


async def test_forged_and_revoked_session_rejected(app_client, world, api_key_factory, owner_engine):
    row, key = await api_key_factory(world.t)
    await login(app_client, key)
    app_client.cookies.set("cl_staff", f"{row.id}.9999999999.deadbeef", path="/staff")
    assert (await app_client.get("/staff")).status_code == 303
    app_client.cookies.clear()
    await login(app_client, key)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    async with AsyncSession(owner_engine) as s:
        await s.execute(text("update api_key set revoked_at = now()"))
        await s.commit()
    assert (await app_client.get("/staff")).status_code == 303


async def test_card_shows_what_staff_needs(app_client, world, api_key_factory, seed):
    await make_draft(world, seed)
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    html = (await app_client.get("/staff")).text
    for s in ("Nguyễn Văn An", "Khóa IELTS giá bao nhiêu", "Hỏi giá", "Đang so sánh nơi khác",
              "Chào chị, em hỏi lại ạ", "Cửa sổ đã đóng", "Đã gửi", "Sửa rồi gửi", "Tôi tự làm", "Bỏ", "im 30 ngày"):
        assert s in html, s
    assert any(a.tool == "staff_ui.queue" for a in await rows(world, m.ActionLog))


async def test_human_agent_window_is_labelled(app_client, world, api_key_factory, seed):
    await make_draft(world, seed, age_days=0)
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Conversation).values(last_customer_at=datetime.now(UTC) - timedelta(hours=30)))
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    assert "Chỉ người gõ tay" in (await app_client.get("/staff")).text


async def test_output_is_escaped(app_client, world, api_key_factory, seed):
    await make_draft(world, seed, text="<script>alert(1)</script>")
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    html = (await app_client.get("/staff")).text
    assert "<script>alert" not in html and "&lt;script&gt;" in html


async def test_post_without_csrf_is_403(app_client, world, api_key_factory, seed):
    d = await make_draft(world, seed)
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    for data in ({"action": "sent"}, {"action": "sent", "csrf": "wrong"}):
        assert (await app_client.post(f"/staff/draft/{d.id}", data=data)).status_code == 403
    assert (await app_client.post("/staff/logout", data={})).status_code == 403
    assert (await rows(world, m.Draft))[0].status == "proposed"


async def test_sent_writes_staff_action(app_client, world, api_key_factory, seed):
    d = await make_draft(world, seed)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    await login(app_client, key)
    tok = csrf_of((await app_client.get("/staff")).text)
    r = await app_client.post(f"/staff/draft/{d.id}", data={"action": "sent", "csrf": tok})
    assert r.status_code == 303 and "msg=ok" in r.headers["location"]
    (sa,) = await rows(world, m.StaffAction)
    assert sa.action == "sent" and sa.staff_ref == "nv1"
    assert "Không có việc nào" in (await app_client.get("/staff")).text


async def test_edited_and_stale(app_client, world, api_key_factory, seed, message_factory):
    d = await make_draft(world, seed)
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    tok = csrf_of((await app_client.get("/staff")).text)
    await message_factory(world.conv, "Khoan, em đổi ý", sender_role="customer")  # customer spoke after draft
    r = await app_client.post(f"/staff/draft/{d.id}", data={"action": "edited", "edited_text": "x", "csrf": tok})
    assert "msg=STALE" in r.headers["location"]
    assert (await rows(world, m.Draft))[0].status == "proposed"
    r = await app_client.post(f"/staff/draft/{d.id}", data={"action": "self", "csrf": tok})
    assert "msg=ok" in r.headers["location"] and (await rows(world, m.StaffAction))[0].action == "self"


async def test_rls_other_tenant_sees_nothing(app_client, world, api_key_factory, seed, tenant_factory):
    await make_draft(world, seed, text="Nháp bí mật của A")
    b = await tenant_factory("B")
    _, key_b = await api_key_factory(b)
    await login(app_client, key_b)
    page = await app_client.get("/staff")
    assert "Nháp bí mật" not in page.text and "Nguyễn Văn An" not in page.text
    assert (await app_client.get(f"/staff/c/{world.conv.id}")).status_code == 404
    d = (await rows(world, m.Draft))[0]
    await app_client.post(f"/staff/draft/{d.id}", data={"action": "skipped", "csrf": csrf_of(page.text)})
    assert (await rows(world, m.Draft))[0].status == "proposed"


async def test_conversation_page(app_client, world, api_key_factory):
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    r = await app_client.get(f"/staff/c/{world.conv.id}")
    assert r.status_code == 200 and "Nguyễn Văn An" in r.text and "IELTS giá bao nhiêu" in r.text
    assert any(a.tool == "staff_ui.conversation" for a in await rows(world, m.ActionLog))


async def test_memory_buttons(app_client, world, api_key_factory):
    svc = pytest.importorskip("cortex_leads.memory.service")
    assert svc
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    await login(app_client, key)
    html = (await app_client.get(f"/staff/c/{world.conv.id}")).text
    tok = csrf_of(html)
    for label in ("Khách hẹn ngày", "Đã gọi", "Đã chuyển Zalo", "Đã chốt", "Đã đặt lịch", "Mua chỗ khác", "Mở lại"):
        assert label in html
    when = (datetime.now(UTC) + timedelta(days=5)).date().isoformat()
    url = f"/staff/c/{world.conv.id}/do"
    assert "msg=ok" in (await app_client.post(url, data={"op": "promise", "value": when, "csrf": tok})).headers["location"]
    assert (await app_client.post(url, data={"op": "promise", "value": when})).status_code == 403
    assert "msg=ok" in (await app_client.post(url, data={"op": "offchannel", "value": "phone", "csrf": tok})).headers["location"]
    assert "msg=ok" in (await app_client.post(url, data={"op": "outcome", "value": "won", "csrf": tok})).headers["location"]
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.Conversation.state))).scalar_one() == "won"


async def test_memory_calls_use_agreed_signatures(app_client, world, api_key_factory, monkeypatch):
    """Runs without WP9: a stub with the PLAN §8.2 signatures records what the page calls."""
    from types import SimpleNamespace

    from cortex_leads.staff_ui import routes
    calls = []

    def rec(name):
        async def f(session, *a, **kw):
            calls.append((name, a, kw))
            return []
        return f
    stub = SimpleNamespace(**{n: rec(n) for n in (
        "record_fact", "record_outcome", "mark_offchannel", "list_facts", "pending_confirmations",
        "confirm_fact", "reject_fact")})
    monkeypatch.setattr(routes, "_memory", lambda: stub)
    _, key = await api_key_factory(world.t, staff_ref="nv1")
    await login(app_client, key)
    tok = csrf_of((await app_client.get(f"/staff/c/{world.conv.id}")).text)
    url = f"/staff/c/{world.conv.id}/do"
    await app_client.post(url, data={"op": "promise", "value": "2030-01-02", "csrf": tok})
    await app_client.post(url, data={"op": "offchannel", "value": "zalo_personal", "csrf": tok})
    await app_client.post(url, data={"op": "outcome", "value": "reopen", "csrf": tok})
    fid = world.conv.id
    r = await app_client.post(f"/staff/fact/{fid}/confirm", data={"csrf": tok, "back": "//evil.com"})
    assert r.headers["location"].startswith("/staff?")  # open-redirect guard
    await app_client.post(f"/staff/fact/{fid}/reject", data={"csrf": tok})
    by = {n: kw for n, _, kw in calls}
    assert by["record_fact"]["kind"] == "promised_date" and by["record_fact"]["source"] == "staff:nv1"
    assert by["record_fact"]["value"] == {"date": "2030-01-02"} and by["record_fact"]["evidence_msg_ids"] == []
    assert by["mark_offchannel"]["channel"] == "zalo_personal" and by["mark_offchannel"]["staff_ref"] == "nv1"
    assert by["record_outcome"]["status"] == "reopen"
    assert by["confirm_fact"]["staff_ref"] == "nv1" and "reject_fact" in by


async def test_waiting_customer_drafts_come_first_and_handoff_is_labelled(app_client, world, api_key_factory, seed):
    await make_draft(world, seed, text="NHÁP CŨ", age_days=0)
    run = await seed(m.TriggerRun(tenant_id=world.t.id, sandbox_id=world.sb.id, skill_name="tra-loi-khach",
                                  skill_version=1, profile="customer_drafter", profile_version=1,
                                  event_type="conversation.awaiting_reply", status="ok", blocked_codes=[]))
    for text, human in (("NHÁP LƯỢT", False), ("NHÁP CHUYỂN NGƯỜI", True)):
        await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id,
                           run_id=run.id, status="proposed", text=text, claims=[], needs_human=human))
    _, key = await api_key_factory(world.t)
    await login(app_client, key)
    html = (await app_client.get("/staff")).text
    assert html.index("NHÁP LƯỢT") < html.index("NHÁP CŨ") and html.index("NHÁP CHUYỂN NGƯỜI") < html.index("NHÁP CŨ")
    assert "Khách đang chờ trả lời" in html and "Cần người trả lời" in html
