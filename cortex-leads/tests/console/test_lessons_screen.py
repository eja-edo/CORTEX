"""WP31: the console shows what the lesson_recap sandbox made. Read only; the transcript is served per lesson, never in the list."""
from datetime import UTC, datetime

from support import h, sign_in

from cortex_leads.db import models as m

RECAP = {"summary": "Lớp học thì hiện tại hoàn thành và làm bài luyện tập.", "topics": ["Thì hiện tại hoàn thành"],
         "homework": [{"task": "Bài 3 và bài 4 trang 45", "due": "thứ Sáu"}], "class_notes": "Cả lớp theo kịp bài."}


async def as_(app_client, world, api_key_factory, role):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def lesson(seed, world, **kw):
    """One sandbox and source per tenant, as the CLI makes them; `kw` sets the lesson."""
    sb = kw.pop("sb", None) or await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap",
                                                    profile_ref="lesson_recapper@1"))
    src = kw.pop("src", None) or await seed(m.Class(tenant_id=world.t.id, recap_sandbox_id=sb.id, source_kind="local", source_ref="/x", name="/x", listed=False, recap_mode="auto"))
    kw = {"status": "done", "file_id": "f1", "name": "Lớp A1 - buổi 5.mp4", **kw}
    row = await seed(m.Lesson(tenant_id=world.t.id, sandbox_id=sb.id, class_id=src.id,
                              created_at=datetime(2026, 10, 22, 2, 0, tzinfo=UTC), **kw))
    return row, sb, src


async def test_the_list_has_status_and_no_transcript(app_client, world, api_key_factory, seed):
    _, sb, src = await lesson(seed, world, recap=RECAP, transcript="lời của cả lớp")
    await lesson(seed, world, sb=sb, src=src, file_id="f2", name="b.mp4", status="failed", error="BAD_SHAPE", attempts=3)
    await lesson(seed, world, sb=sb, src=src, file_id="f3", name="c.mp4", status="failed", error="TRANSCRIBE_CortexError")
    await as_(app_client, world, api_key_factory, "owner")
    r = (await app_client.get("/api/v1/lessons")).json()
    assert {x["name"] for x in r["items"]} == {"Lớp A1 - buổi 5.mp4", "b.mp4", "c.mp4"}
    done = next(x for x in r["items"] if x["has_recap"])
    assert done["status_label"] == "Xong" and done["sandbox"] == "Tổng kết buổi học" and done["created_at"] == "2026-10-22T02:00:00Z"
    assert "lời của cả lớp" not in str(r)
    bad = {x["problem"] for x in r["items"] if x["status"] == "failed"}
    assert bad == {"AI trả lời sai khuôn, sẽ thử lại", "Lỗi khi chuyển giọng nói thành chữ"}


async def test_one_lesson_has_its_recap_message_and_transcript(app_client, world, api_key_factory, seed):
    row, *_ = await lesson(seed, world, recap=RECAP, transcript="lời của cả lớp")
    await as_(app_client, world, api_key_factory, "owner")  # the teaching team, not only the owner
    d = (await app_client.get(f"/api/v1/lessons/{row.id}")).json()
    assert d["recap"]["homework"][0]["task"] == "Bài 3 và bài 4 trang 45" and d["transcript"] == "lời của cả lớp"
    assert "Bản nháp do AI" in d["message"] and "(hạn: thứ Sáu)" in d["message"]


async def test_a_lesson_of_another_business_is_not_found(app_client, world, api_key_factory, seed, tenant_factory):
    other = await tenant_factory("Khác")
    sb = await seed(m.Sandbox(tenant_id=other.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1"))
    src = await seed(m.Class(tenant_id=other.id, recap_sandbox_id=sb.id, source_kind="local", source_ref="/y", name="/y", listed=False, recap_mode="auto"))
    theirs = await seed(m.Lesson(tenant_id=other.id, sandbox_id=sb.id, class_id=src.id, file_id="z", name="z.mp4", status="done", recap=RECAP))
    await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.get(f"/api/v1/lessons/{theirs.id}")).status_code == 404
    assert (await app_client.get("/api/v1/lessons")).json()["items"] == []


async def test_nobody_signed_out_reads_lessons(app_client, world):
    assert (await app_client.get("/api/v1/lessons")).status_code in (401, 403)


async def test_the_lesson_skill_is_listed_with_its_own_trigger_not_a_silent_customer(app_client, world, api_key_factory, seed):
    from cortex_leads.db.session import tenant_session
    from cortex_leads.skills.loader import sync_dir
    from cortex_leads.skills.profile import SANDBOXES_DIR
    from cortex_leads.skills.registry import promote
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="lesson_recap", purpose="lesson_recap", profile_ref="lesson_recapper@1"))
    async with tenant_session(world.t.id) as s:
        for row in await sync_dir(s, world.t.id, sb.id, SANDBOXES_DIR / "lesson_recap" / "skills"):
            await promote(s, sb.id, row.name, row.version, "shadow")
            await promote(s, sb.id, row.name, row.version, "live")
    await as_(app_client, world, api_key_factory, "owner")
    mine = next(x for x in (await app_client.get("/api/v1/skills")).json()["items"] if x["name"] == "tom-tat-buoi-hoc")
    assert mine["trigger"] == "Có bản ghi buổi học mới" and mine["sandbox"] == "Tổng kết buổi học"


async def test_a_drive_lesson_offers_its_video(app_client, world, api_key_factory, seed):
    row, *_ = await lesson(seed, world, recap=RECAP, transcript="x", file_id="abc123")
    from sqlalchemy import text as sql

    from cortex_leads.db.session import tenant_session
    async with tenant_session(world.t.id) as s:
        await s.execute(sql("update class set source_kind = 'drive'"))
    await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/lessons/{row.id}")).json()
    assert d["video_url"] == "https://drive.google.com/file/d/abc123/view" and d["message"].endswith(d["video_url"])


async def test_the_sandbox_pages_say_what_goes_in_and_where_it_goes_without_ever_showing_an_address(app_client, world, api_key_factory, seed):
    from sqlalchemy import text as sql

    from cortex_leads.db.session import tenant_session
    row, sb, src = await lesson(seed, world, recap=RECAP, transcript="x", status="done")
    await lesson(seed, world, sb=sb, src=src, file_id="f2", name="b.mp4", status="failed", error="BAD_SHAPE")
    await lesson(seed, world, sb=sb, src=src, file_id="f3", name="c.mp4", status="queued")
    secret = "https://webhook.mezon.ai/webhooks/111/TOKEN-THAT-MUST-NOT-APPEAR"
    await seed(m.NotifyTarget(tenant_id=world.t.id, kind="mezon", address=secret, label="Mezon của đội"))
    async with tenant_session(world.t.id) as s:
        await s.execute(sql("update class set source_kind = 'drive', source_ref = 'abcdefghijklmnop123456', drive_account_id = null"))
    await as_(app_client, world, api_key_factory, "owner")

    d = (await app_client.get(f"/api/v1/sandboxes/{sb.id}")).json()
    assert d["facing"] == {"customer": False, "tools": False}
    (feed,) = d["feeds"]
    assert feed["label"] == "Thư mục Google Drive" and feed["where"] == "…123456" and feed["lessons"] == {"done": 1, "failed": 1, "waiting": 1}
    assert d["pushes"] == [{"id": d["pushes"][0]["id"], "kind": "mezon", "label": "Mezon của đội", "where": "webhook.mezon.ai", "active": True}]
    assert "TOKEN-THAT-MUST-NOT-APPEAR" not in str(d) and "abcdefghijklmnop" not in str(d)  # neither the token nor the folder id
    assert d["skills"] == []  # no skill synced in this fixture; with one, its trigger is the Skills page's wording (tested there)

    listing = (await app_client.get("/api/v1/sandboxes")).json()["items"]
    mine = next(x for x in listing if x["id"] == str(sb.id))
    assert mine["customer_facing"] is False and mine["flow"] == "1 thư mục bản ghi → 1 kênh Mezon"
    care = next(x for x in listing if x["purpose"] == "customer_care")
    assert care["customer_facing"] is True and care["flow"] is None


async def test_a_customer_care_sandbox_still_has_its_tools_send_mode_and_catalogue(app_client, world, api_key_factory):
    await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).json()
    assert d["facing"] == {"customer": True, "tools": True} and d["feeds"] == [] and d["pushes"] == [] and d["tools"]


async def test_every_event_a_shipped_skill_listens_to_has_its_own_words_not_the_customer_one():
    """The default label says "Khách im 24 giờ": a skill about a student's work or a lesson must never read like that."""
    from cortex_leads.console.skills import trigger_text
    from cortex_leads.core.vocabulary import EVENT_TYPES
    default = trigger_text({"trigger": {"on": "conversation.silent"}})
    own = {e: trigger_text({"trigger": {"on": e}}) for e in ("lesson.recorded", "submission.turned_in", "assignment.requested")}
    assert default == "Khách im 24 giờ" and all(t != default for t in own.values()) and len(set(own.values())) == 3
    assert {"lesson.recorded", "submission.turned_in", "assignment.requested"} <= EVENT_TYPES


async def test_a_recap_a_class_holds_is_released_by_the_teaching_team_once_and_goes_to_the_channel(app_client, world, api_key_factory, seed):
    from sqlalchemy import select

    from cortex_leads.db.session import tenant_session
    row, *_ = await lesson(seed, world, recap=RECAP, transcript="x")
    await seed(m.NotifyTarget(tenant_id=world.t.id, kind="mezon", address="https://webhook.mezon.ai/hooks/x", label="Đội"))
    csrf = await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/lessons/{row.id}")).json()
    assert d["awaiting_release"] is True and d["released"] is False
    r = await app_client.post(f"/api/v1/lessons/{row.id}/release", headers=h(csrf))
    assert r.status_code == 200, r.text
    d = (await app_client.get(f"/api/v1/lessons/{row.id}")).json()
    assert d["awaiting_release"] is False and d["released"] is True and d["released_by"]
    async with tenant_session(world.t.id) as s:
        assert [n.kind for n in (await s.execute(select(m.Notification))).scalars()] == ["lesson"]  # told to the team, once
    again = await app_client.post(f"/api/v1/lessons/{row.id}/release", headers=h(csrf))
    assert again.status_code == 409 and again.json()["detail"]["code"] == "ALREADY_RELEASED"


async def test_a_lesson_with_no_recap_yet_cannot_be_released(app_client, world, api_key_factory, seed):
    row, *_ = await lesson(seed, world, status="working")
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post(f"/api/v1/lessons/{row.id}/release", headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_READY"
