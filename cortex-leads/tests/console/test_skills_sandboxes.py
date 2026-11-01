"""WP27 Kỹ năng and Sandbox endpoints."""
from support import h, sign_in
from wp5_support import rows

from cortex_leads.db import models as m

FORM = {"template": "khach_im", "slug": "nhac-gia", "description": "Hỏi lại khách đã hỏi giá rồi im quá nửa ngày",
        "instructions": "Nhắc nhẹ, nêu đúng một lợi ích của khoá khách quan tâm, không thúc ép chốt.",
        "after_hours": 4, "intent": "hoi_gia", "max_touches": 1, "never_say": ["giá sốc"], "must_handoff": ["bảo hành"]}


async def as_(app_client, world, api_key_factory, role):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def trial_runs(world, seed, name, n):
    for _ in range(n):
        await seed(m.TriggerRun(tenant_id=world.t.id, sandbox_id=world.sb.id, skill_name=name, skill_version=1, profile="customer_drafter",
                                profile_version=1, event_type="conversation.silent", status="ok", blocked_codes=[]))


# --- skills -------------------------------------------------------------------------------------
async def test_listing_shows_the_shipped_skills_with_plain_triggers_and_what_may_be_done(app_client, world, api_key_factory):
    await as_(app_client, world, api_key_factory, "staff")
    r = (await app_client.get("/api/v1/skills")).json()
    by = {i["name"]: i for i in r["items"]}
    assert by["hoi-lai-khach-im"]["trigger"] == "Khách im 20 giờ (Hỏi giá)" and by["hoi-lai-khach-im"]["status"] == "live"
    assert by["tra-loi-khach"]["trigger"] == "Khách nhắn xong, chưa ai trả lời"
    assert by["hoi-lai-dung-hen"]["trigger"] == "Tới ngày khách đã hẹn" and by["hoi-lai-dung-hen"]["source"] == "system"
    assert not any(by["hoi-lai-khach-im"]["can"].values())  # a shipped live skill is not switched off from here
    assert r["counts"]["live"] == 2 and r["min_trial_runs"] == 10


async def test_form_options_offer_the_templates_and_the_domain_intents(app_client, world, api_key_factory):
    await as_(app_client, world, api_key_factory, "staff")
    o = (await app_client.get("/api/v1/skills/form-options")).json()
    assert {t["id"] for t in o["templates"]} == {"khach_im", "dung_hen"} and {"id": "hoi_gia", "label": "Hỏi giá"} in o["intents"]
    assert o["has_sandbox"] and "Tự gửi tin cho khách (chỉ soạn nháp)" in o["locked"]


async def test_preview_reports_lint_errors_and_a_safe_summary_without_saving(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    ok = (await app_client.post("/api/v1/skills/preview", json=FORM, headers=h(csrf))).json()
    assert ok["errors"] == [] and ok["summary"]["trigger"] == "Khách im 4 giờ (Hỏi giá)"
    assert "Soạn nháp cho nhân viên duyệt" in ok["summary"]["tools"] and "Gửi tin cho khách" not in ok["summary"]["tools"]
    assert ok["summary"]["must_handoff"][-1] == "bảo hành" and ok["summary"]["never_say_count"] > 20
    bad = (await app_client.post("/api/v1/skills/preview", json={**FORM, "intent": "khong-co"}, headers=h(csrf))).json()
    assert any("not in the domain pack" in e for e in bad["errors"])
    assert not [v for v in await rows(world, m.SkillVersion) if v.name.startswith("tuy-chinh")]


async def test_create_validates_and_rejects_what_the_form_must_never_carry(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    r = await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))
    assert r.status_code == 201 and r.json()["name"] == "tuy-chinh-nhac-gia" and r.json()["version"] == 1
    for extra in ({"requires_tools": ["send_message"]}, {"send_policy": {"mode": "auto"}}, {"slug": "Bad Slug"}, {"after_hours": 1}):
        assert (await app_client.post("/api/v1/skills", json={**FORM, **extra}, headers=h(csrf))).status_code == 422, extra
    r = await app_client.post("/api/v1/skills", json={**FORM, "slug": "khac", "intent": "khong-co"}, headers=h(csrf))
    assert r.status_code == 422 and "errors" in r.json()["detail"]
    assert [v.name for v in await rows(world, m.SkillVersion) if v.name.startswith("tuy-chinh")] == ["tuy-chinh-nhac-gia"]
    assert (await app_client.post("/api/v1/skills", json=FORM)).status_code == 403  # no CSRF


async def test_the_lifecycle_is_the_owners_and_going_live_needs_the_trial_runs(app_client, world, api_key_factory, seed):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    assert (await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))).status_code == 403  # staff
    csrf = await as_(app_client, world, api_key_factory, "owner")
    item = next(i for i in (await app_client.get("/api/v1/skills")).json()["items"] if i["id"] == sid)
    assert item["status"] == "draft" and item["can"] == {"trial": True, "live": False, "off": False, "again": False, "edit": True, "delete": True, "restore": False}
    assert (await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))).json() == {"status": "shadow"}
    r = await app_client.post(f"/api/v1/skills/{sid}/live", headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "SKILL_RULE" and "needs 10 trial runs" in r.json()["detail"]["message"]
    await trial_runs(world, seed, "tuy-chinh-nhac-gia", 10)
    d = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert d["runs"] == 10 and d["ready"] and d["can"]["live"] and d["sends"] is False
    assert (await app_client.post(f"/api/v1/skills/{sid}/live", headers=h(csrf))).json() == {"status": "live"}
    assert (await app_client.post(f"/api/v1/skills/{sid}/off", headers=h(csrf))).json() == {"status": "retired"}
    assert (await app_client.post(f"/api/v1/skills/{sid}/again", headers=h(csrf))).json() == {"status": "live"}
    shipped = next(v for v in await rows(world, m.SkillVersion) if v.name == "hoi-lai-khach-im" and v.status == "live")
    assert (await app_client.post(f"/api/v1/skills/{shipped.id}/off", headers=h(csrf))).status_code == 404  # never a shipped skill


async def test_detail_shows_the_trial_drafts_and_the_safety_summary(app_client, world, api_key_factory, seed):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))
    run = await seed(m.TriggerRun(tenant_id=world.t.id, sandbox_id=world.sb.id, skill_name="tuy-chinh-nhac-gia", skill_version=1,
                                  profile="customer_drafter", profile_version=1, event_type="conversation.silent", status="ok", blocked_codes=[]))
    await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, run_id=run.id, status="shadow",
                       text="Chị ơi lớp IELTS còn chỗ ạ", claims=[], reason_code="khong_ro"))
    await seed(m.Draft(tenant_id=world.t.id, sandbox_id=world.sb.id, conversation_id=world.conv.id, run_id=run.id, status="blocked",
                       text="Giá 1.000.000đ thôi", claims=[], reason_code="khong_ro"))
    d = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert sorted((t["blocked"], t["text"][:8]) for t in d["trial_drafts"]) == [(False, "Chị ơi l"), (True, "Giá 1.00")]
    assert d["trial_drafts"][0]["asked"].startswith("Chào shop")
    assert d["tools"][-1] == "Soạn nháp cho nhân viên duyệt" and "giảm giá" in d["must_handoff"] and d["never_say_count"] > 20
    assert (await app_client.get("/api/v1/skills/00000000-0000-0000-0000-000000000000")).status_code == 404


# --- sandboxes ----------------------------------------------------------------------------------
async def test_sandbox_list_has_usage_budget_skills_and_the_template_catalogue(app_client, world, api_key_factory, seed):
    await as_(app_client, world, api_key_factory, "staff")
    await trial_runs(world, seed, "x", 3)
    r = (await app_client.get("/api/v1/sandboxes")).json()
    (sb,) = r["items"]
    assert sb["title"] == "Chăm sóc khách" and sb["purpose"] == "customer_care" and "khách tiềm năng" in sb["about"] and sb["status"] == "active" and sb["send_mode"] == "manual"
    assert sb["usage"]["runs"] == 3 and sb["budget"]["runs_per_day"] == 100 and sb["skills"]["live"] == 2 and sb["channels"] == [
        {"kind": "messenger", "status": "active", "sends": False}]
    tpl = {t["id"]: t for t in r["templates"]}
    assert tpl["customer_care"]["available"] and tpl["owner_digest"]["available"]
    assert tpl["student_care"]["available"] is False and "chờ trung tâm" in tpl["student_care"]["reason"]


async def test_creating_a_sandbox_is_the_owners_and_comes_up_ready_but_safe(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.post("/api/v1/sandboxes", json={"template": "customer_care", "title": "Cơ sở 2"}, headers=h(csrf))).status_code == 403
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/sandboxes", json={"template": "customer_care", "title": "Chăm sóc khách – cơ sở 2"}, headers=h(csrf))
    assert r.status_code == 201 and r.json()["name"] == "customer_care-2"
    new = next(s for s in await rows(world, m.Sandbox) if s.title)
    assert (new.title, new.purpose, new.send_mode, new.status) == ("Chăm sóc khách – cơ sở 2", "customer_care", "manual", "active")
    assert new.profile_ref == "customer_drafter@1" and "hoi_gia" in new.domain_pack["intents"]
    live = sorted(v.name for v in await rows(world, m.SkillVersion) if v.sandbox_id == new.id and v.status == "live")
    assert {"tra-loi-khach", "hoi-lai-khach-im", "hoi-lai-dung-hen"} <= set(live)
    r = await app_client.post("/api/v1/sandboxes", json={"template": "owner_digest", "title": "Báo cáo cho chủ"}, headers=h(csrf))
    assert r.status_code == 201 and next(s for s in await rows(world, m.Sandbox) if s.purpose == "owner_digest").profile_ref == "digest_template@1"
    assert "sandbox.created" in [a.action for a in await rows(world, m.AuditEvent)]


async def test_the_unopened_template_and_bad_titles_are_refused(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    r = await app_client.post("/api/v1/sandboxes", json={"template": "student_care", "title": "Hỗ trợ học viên"}, headers=h(csrf))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "NOT_AVAILABLE"
    for body in ({"template": "customer_care", "title": "ab"}, {"template": "nope", "title": "Tên hợp lệ"}):
        assert (await app_client.post("/api/v1/sandboxes", json=body, headers=h(csrf))).status_code == 422
    assert len(await rows(world, m.Sandbox)) == 1


async def test_a_renamed_sandbox_still_finds_its_style_and_skills_by_purpose(app_client, world, api_key_factory):
    from cortex_leads.skills.forms import FormSpec, _house_never_say
    from cortex_leads.skills.profile import template_dir
    csrf = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post("/api/v1/sandboxes", json={"template": "customer_care", "title": "Tên tự do hoàn toàn"}, headers=h(csrf))
    new = next(s for s in await rows(world, m.Sandbox) if s.title)
    assert template_dir(new) == "customer_care" and len(_house_never_say(template_dir(new))) > 20
    assert FormSpec  # (the form builds its house rules from the template folder, not from the sandbox's name)


async def test_pausing_one_sandbox_leaves_the_others(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    await app_client.post("/api/v1/sandboxes", json={"template": "owner_digest", "title": "Báo cáo cho chủ"}, headers=h(csrf))
    care = world.sb.id
    assert (await app_client.post(f"/api/v1/sandboxes/{care}/pause", headers=h(csrf))).json() == {"status": "paused"}
    assert sorted(s.status for s in await rows(world, m.Sandbox)) == ["active", "paused"]
    assert (await app_client.post(f"/api/v1/sandboxes/{care}/resume", headers=h(csrf))).json() == {"status": "active"}
    assert (await app_client.post("/api/v1/sandboxes/00000000-0000-0000-0000-000000000000/pause", headers=h(csrf))).status_code == 404
    csrf = await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.post(f"/api/v1/sandboxes/{care}/pause", headers=h(csrf))).status_code == 403


async def test_a_form_skill_is_edited_in_place_and_the_old_form_is_kept_in_the_log(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    d = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert d["form"]["instructions"] == FORM["instructions"] and d["form"]["after_hours"] == FORM["after_hours"]  # the form as filled
    new = {**d["form"], "instructions": "Nhắc nhẹ, nhắc đúng khoá khách đã hỏi, không hối thúc khách.", "after_hours": 30}
    r = await app_client.put(f"/api/v1/skills/{sid}", json=new, headers=h(csrf))
    assert r.status_code == 200 and r.json()["version"] == 1 and r.json()["status"] == "draft"
    mine = [v for v in await rows(world, m.SkillVersion) if v.name == "tuy-chinh-nhac-gia"]
    assert len(mine) == 1  # no new version
    assert mine[0].manifest["trigger"]["after"] == "30h" and "hối thúc" in mine[0].body and mine[0].form_spec["after_hours"] == 30
    ev = [e for e in await rows(world, m.AuditEvent) if e.action == "skill.edited"]
    assert len(ev) == 1 and ev[0].metadata_["before_spec"]["after_hours"] == FORM["after_hours"]
    assert {c["field"] for c in ev[0].metadata_["changes"]} == {"instructions", "after_hours"}
    hist = (await app_client.get(f"/api/v1/skills/{sid}")).json()["history"]
    assert hist[0]["summary"].startswith("Sửa kỹ năng") and hist[0]["changes"]
    assert (await app_client.put(f"/api/v1/skills/{sid}", json={**new, "slug": "doi-ten"}, headers=h(csrf))).status_code == 422  # name is identity
    assert (await app_client.put(f"/api/v1/skills/{sid}", json={**new, "after_hours": 1}, headers=h(csrf))).status_code == 422


async def test_staff_may_edit_a_draft_but_not_a_skill_that_is_on(app_client, world, api_key_factory, seed):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    form = (await app_client.get(f"/api/v1/skills/{sid}")).json()["form"]
    assert (await app_client.put(f"/api/v1/skills/{sid}", json=form, headers=h(csrf))).status_code == 200
    csrf = await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))).status_code == 200
    csrf = await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.put(f"/api/v1/skills/{sid}", json=form, headers=h(csrf))).status_code == 403
    csrf = await as_(app_client, world, api_key_factory, "owner")
    assert (await app_client.put(f"/api/v1/skills/{sid}", json=form, headers=h(csrf))).status_code == 200  # owner, on trial


async def test_deleting_a_skill_hides_and_switches_it_off_and_it_can_be_restored(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))
    assert (await app_client.post(f"/api/v1/skills/{sid}/restore", headers=h(csrf))).status_code == 409  # not deleted
    assert (await app_client.post(f"/api/v1/skills/{sid}/delete", headers=h(csrf))).status_code == 200
    row = next(v for v in await rows(world, m.SkillVersion) if v.name == "tuy-chinh-nhac-gia")
    assert row.status == "retired" and row.deleted_at is not None and row.deleted_by == "staff:owner"  # the row stays
    lst = (await app_client.get("/api/v1/skills")).json()
    gone = next(i for i in lst["items"] if i["id"] == sid)
    assert gone["deleted"] and lst["counts"]["deleted"] == 1 and lst["counts"]["all"] == sum(1 for i in lst["items"] if not i["deleted"])
    assert gone["can"] == {"trial": False, "live": False, "off": False, "again": False, "edit": False, "delete": False, "restore": True}
    assert (await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))).status_code == 409
    assert (await app_client.put(f"/api/v1/skills/{sid}", json=FORM, headers=h(csrf))).status_code == 404
    assert (await app_client.post(f"/api/v1/skills/{sid}/restore", headers=h(csrf))).status_code == 200
    back = next(i for i in (await app_client.get("/api/v1/skills")).json()["items"] if i["id"] == sid)
    assert not back["deleted"] and back["status"] == "retired" and back["can"]["again"]  # back, but still off
    assert {e.action for e in await rows(world, m.AuditEvent)} >= {"skill.delete", "skill.restore"}


async def test_a_shipped_skill_cannot_be_deleted(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    lst = (await app_client.get("/api/v1/skills")).json()["items"]
    shipped = next((i for i in lst if i["source"] == "system"), None)
    if shipped:
        assert (await app_client.post(f"/api/v1/skills/{shipped['id']}/delete", headers=h(csrf))).status_code == 404


async def test_an_edit_restarts_the_trial_count_and_a_change_can_be_put_back(app_client, world, api_key_factory, seed):
    csrf = await as_(app_client, world, api_key_factory, "owner")
    sid = (await app_client.post("/api/v1/skills", json=FORM, headers=h(csrf))).json()["id"]
    await app_client.post(f"/api/v1/skills/{sid}/trial", headers=h(csrf))
    await trial_runs(world, seed, "tuy-chinh-nhac-gia", 10)
    assert (await app_client.get(f"/api/v1/skills/{sid}")).json()["runs"] == 10
    form = (await app_client.get(f"/api/v1/skills/{sid}")).json()["form"]
    await app_client.put(f"/api/v1/skills/{sid}", json={**form, "after_hours": 40}, headers=h(csrf))
    d = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert d["runs"] == 0 and d["can"]["live"] is False  # the ten runs tried the old text
    assert (await app_client.post(f"/api/v1/skills/{sid}/live", headers=h(csrf))).status_code == 409
    ev = d["history"][0]
    assert ev["restorable"]
    r = await app_client.post(f"/api/v1/skills/{sid}/revert", json={"event_id": ev["id"]}, headers=h(csrf))
    assert r.status_code == 200
    back = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert back["form"]["after_hours"] == FORM["after_hours"] and back["history"][0]["summary"].startswith("Khôi phục")
    assert (await app_client.post(f"/api/v1/skills/{sid}/revert", json={"event_id": "00000000-0000-0000-0000-000000000000"}, headers=h(csrf))).status_code == 404
