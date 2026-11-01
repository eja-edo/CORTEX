"""WP29: tools per sandbox, the permission matrix, and the switch that the runner honours."""
from support import h, sign_in
from wp5_support import rows

from cortex_leads.db import models as m

FORM = {"template": "khach_im", "slug": "nhac-gia", "description": "Hỏi lại khách đã hỏi giá rồi im quá nửa ngày",
        "instructions": "Nhắc nhẹ, nêu đúng một lợi ích của khoá khách quan tâm, không thúc ép chốt.",
        "after_hours": 4, "intent": "hoi_gia", "max_touches": 1, "never_say": [], "must_handoff": []}


async def as_(app_client, world, api_key_factory, role):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def test_the_catalogue_lists_tools_with_their_level_and_where_they_run(app_client, world, api_key_factory):
    await as_(app_client, world, api_key_factory, "owner")
    r = (await app_client.get("/api/v1/tools")).json()
    by = {t["name"]: t for t in r["items"]}
    assert by["send_message"]["level"] == "customer" and by["book_slot"]["level"] == "internal" and by["read_messages"]["level"] == "read"
    assert by["read_messages"]["label"] == "Đọc tin nhắn" and by["read_messages"]["skills"] >= 1
    assert [x["on"] for x in by["send_message"]["sandboxes"]] == [True]
    assert r["levels"]["external"] == "Dữ liệu ngoài"


async def test_tools_are_the_owners_page(app_client, world, api_key_factory):
    await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.get("/api/v1/tools")).status_code == 403
    assert (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).status_code == 403


async def test_the_matrix_is_the_meeting_of_the_sandbox_and_what_each_skill_declares(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))
    sid = next(v for v in await rows(world, m.SkillVersion) if v.name == "tuy-chinh-nhac-gia").id
    await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))
    d = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).json()
    assert d["profile"]["id"] == "customer_drafter" and d["profile"]["ceiling"] == "Gửi khách"
    by = {s["name"]: s for s in d["skills"]}
    assert by["hoi-lai-khach-im"]["cells"]["lookup_catalog"] == "uses" and by["hoi-lai-khach-im"]["cells"]["send_message"] in ("uses", "allowed")
    mine = by["tuy-chinh-nhac-gia"]
    assert mine["cells"]["send_message"] == "locked" and mine["cells"]["book_slot"] == "locked"  # a form skill can never use these
    assert mine["cells"]["read_messages"] == "uses" and mine["cells"]["study_plan"] == "locked"
    assert by["hoi-lai-khach-im"]["cells"]["study_plan"] in ("allowed", "uses")  # the sandbox allows it
    assert d["inputs"]["catalog_items"] >= 0 and d["inputs"]["channels"][0]["kind"] == "messenger"


async def test_switching_a_tool_off_is_audited_and_shows_as_blocked_for_the_skills_that_need_it(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/tools/lookup_catalog/off", headers=h(csrf))).json() == {"tool": "lookup_catalog", "on": False}
    assert (await rows(world, m.Sandbox))[0].tools_off == ["lookup_catalog"]
    d = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).json()
    assert next(s for s in d["skills"] if s["name"] == "hoi-lai-khach-im")["cells"]["lookup_catalog"] == "blocked"
    assert next(t for t in d["tools"] if t["name"] == "lookup_catalog")["on"] is False
    one = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}/tools/lookup_catalog")).json()
    assert "hoi-lai-khach-im" in one["if_off"]
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "tool.off"]
    assert len(ev) == 1 and ev[0].metadata_["tools_off_after"] == ["lookup_catalog"]
    await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/tools/lookup_catalog/off", headers=h(csrf))  # again: no second line
    assert len([e for e in await rows(world, m.AuditEvent) if e.action == "tool.off"]) == 1
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/tools/lookup_catalog/on", headers=h(csrf))).json()["on"] is True
    assert (await rows(world, m.Sandbox))[0].tools_off == []


async def test_a_tool_outside_the_profile_cannot_be_switched_on_and_a_stranger_sandbox_is_404(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/tools/external_lookup/on", headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "TOOL_NOT_IN_PROFILE"
    assert (await app_client.post("/api/v1/sandboxes/00000000-0000-0000-0000-000000000000/tools/lookup_catalog/off", headers=h(csrf))).status_code == 404


async def test_the_owner_switches_between_manual_and_auto_and_the_page_says_what_auto_really_does(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    d = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).json()["send"]
    assert d["mode"] == "manual"
    by = {s["name"]: s for s in d["skills"]}
    assert by["hoi-lai-khach-im"]["can_auto"] is False and "luôn chờ nhân viên" in by["hoi-lai-khach-im"]["why"]  # never auto, whatever the sandbox says
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "auto"}, headers=h(csrf))).json() == {"send_mode": "auto", "changed": True}
    d = (await app_client.get(f"/api/v1/sandboxes/{world.sb.id}")).json()["send"]
    assert d["mode"] == "auto" and all(s["effective"] == "manual" for s in d["skills"] if not s["can_auto"])
    assert (await app_client.get("/api/v1/session")).json()["mode"] == "auto"  # the sidebar follows
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "auto"}, headers=h(csrf))).json()["changed"] is False
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "manual"}, headers=h(csrf))).json()["send_mode"] == "manual"
    ev = sorted((e for e in await rows(world, m.AuditEvent) if e.action == "send_mode.changed"), key=lambda e: e.seq)
    assert [(e.metadata_["from"], e.metadata_["to"]) for e in ev] == [("manual", "auto"), ("auto", "manual")]
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "sometimes"}, headers=h(csrf))).status_code == 422


async def test_staff_cannot_change_the_send_mode(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.post(f"/api/v1/sandboxes/{world.sb.id}/send-mode", json={"mode": "auto"}, headers=h(csrf))).status_code == 403
    assert (await rows(world, m.Sandbox))[0].send_mode == "manual"
