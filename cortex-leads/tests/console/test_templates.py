"""Class kinds and assignment templates: a business names its kinds of class, each keeps ready-made assignments, the compose form is filled from one."""
from sqlalchemy import select
from support import h, sign_in

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

RUBRIC = [{"id": "y0", "label": "Ý chính", "points": 6, "descriptor": ""}, {"id": "t1", "label": "Trình bày", "points": 4, "descriptor": ""}]
FULL = {"name": "Viết đoạn văn", "title": "Viết đoạn văn về gia đình", "description": "Viết một đoạn văn 8 câu về gia đình em.", "max_points": 10, "criteria": RUBRIC,
        "answer_key": "Bài mẫu…", "check_prompt": "Bỏ qua dấu câu", "language": "vi", "topic_name": "Tuần 1",
        "materials": [{"url": "https://drive.google.com/file/d/abc123/view", "title": "Phiếu", "share": "STUDENT_COPY"}]}


async def as_(app_client, world, api_key_factory, role="owner"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


async def grader_class(world, seed, name="Lớp A"):
    sb = await seed(m.Sandbox(tenant_id=world.t.id, name="classroom_grader", purpose="classroom_grader", profile_ref="classroom_grader@1"))
    return await seed(m.Class(tenant_id=world.t.id, name=name, grader_sandbox_id=sb.id, course_id=f"c-{name}", auth_kind="oauth"))


async def kind(app_client, csrf, name="IELTS"):
    return (await app_client.post("/api/v1/class-kinds", json={"name": name}, headers=h(csrf))).json()


async def test_a_template_keeps_every_field_of_the_compose_form(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory)
    k = await kind(app_client, csrf)
    r = await app_client.post(f"/api/v1/class-kinds/{k['id']}/templates", json=FULL, headers=h(csrf))
    assert r.status_code == 201
    (t,) = (await app_client.get(f"/api/v1/class-kinds/{k['id']}/templates")).json()["items"]
    for f in ("name", "title", "description", "max_points", "answer_key", "check_prompt", "language", "topic_name"):
        assert t[f] == FULL[f], f
    assert [c["id"] for c in t["criteria"]] == ["y0", "t1"] and t["materials"] == FULL["materials"]


async def test_a_template_may_hold_only_some_fields_but_not_a_rubric_that_does_not_add_up(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory)
    k = await kind(app_client, csrf)
    url = f"/api/v1/class-kinds/{k['id']}/templates"
    assert (await app_client.post(url, json={"name": "Chỉ đề"}, headers=h(csrf))).status_code == 201
    assert (await app_client.post(url, json={**FULL, "name": "Lệch", "max_points": 20}, headers=h(csrf))).status_code == 422
    r = await app_client.post(url, json={**FULL, "name": "Link xấu", "materials": [{"url": "ftp://x/y", "share": "VIEW"}]}, headers=h(csrf))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_MATERIAL"


async def test_names_are_unique_per_business_and_per_kind(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory)
    a, b = await kind(app_client, csrf, "IELTS"), await kind(app_client, csrf, "Thiếu nhi")
    assert (await app_client.post("/api/v1/class-kinds", json={"name": "IELTS"}, headers=h(csrf))).status_code == 409
    assert (await app_client.post(f"/api/v1/class-kinds/{a['id']}/templates", json={"name": "Bài 1"}, headers=h(csrf))).status_code == 201
    assert (await app_client.post(f"/api/v1/class-kinds/{a['id']}/templates", json={"name": "Bài 1"}, headers=h(csrf))).status_code == 409
    assert (await app_client.post(f"/api/v1/class-kinds/{b['id']}/templates", json={"name": "Bài 1"}, headers=h(csrf))).status_code == 201  # another kind may reuse a name


async def test_the_form_lists_the_kinds_with_how_many_templates_each_has_and_then_the_templates_of_the_chosen_kind(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory)
    ielts, kids = await kind(app_client, csrf, "IELTS"), await kind(app_client, csrf, "Thiếu nhi")
    await app_client.post(f"/api/v1/class-kinds/{ielts['id']}/templates", json={"name": "Writing task 1"}, headers=h(csrf))
    await app_client.post(f"/api/v1/class-kinds/{ielts['id']}/templates", json={"name": "Speaking part 2"}, headers=h(csrf))
    await app_client.post(f"/api/v1/class-kinds/{kids['id']}/templates", json={"name": "Tô màu"}, headers=h(csrf))
    listed = (await app_client.get("/api/v1/class-kinds")).json()["items"]
    assert {k["name"]: k["templates"] for k in listed} == {"IELTS": 2, "Thiếu nhi": 1}
    assert all(set(k) == {"id", "name", "templates"} for k in listed)  # no class is tied to a kind
    got = (await app_client.get(f"/api/v1/class-kinds/{ielts['id']}/templates")).json()
    assert got["kind"]["name"] == "IELTS" and [t["name"] for t in got["items"]] == ["Speaking part 2", "Writing task 1"]


async def test_a_class_has_no_kind_and_the_old_per_class_endpoint_is_gone(app_client, world, api_key_factory, seed):
    csrf = await as_(app_client, world, api_key_factory)
    cls = await grader_class(world, seed)
    r = await app_client.patch(f"/api/v1/classes/{cls.id}", json={"name": "Lớp A2"}, headers=h(csrf))
    assert r.status_code == 200 and "kind_id" not in r.json()
    assert (await app_client.get(f"/api/v1/classes/{cls.id}/assignment-templates")).status_code == 404


async def test_editing_replaces_the_whole_template_and_deleting_a_kind_takes_its_templates(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory)
    k = await kind(app_client, csrf)
    t = (await app_client.post(f"/api/v1/class-kinds/{k['id']}/templates", json=FULL, headers=h(csrf))).json()
    r = await app_client.put(f"/api/v1/assignment-templates/{t['id']}", json={"name": "Viết đoạn văn", "title": "Mới"}, headers=h(csrf))
    assert r.json()["title"] == "Mới" and r.json()["criteria"] == [] and r.json()["description"] is None  # what the form left empty is cleared
    gone = (await app_client.delete(f"/api/v1/class-kinds/{k['id']}", headers=h(csrf))).json()
    assert gone["templates"] == 1
    async with tenant_session(world.t.id) as s:
        assert (await s.execute(select(m.AssignmentTemplate))).first() is None
        trail = {e.action for e in (await s.execute(select(m.AuditEvent))).scalars()}
    assert {"class_kind.created", "assignment_template.created", "assignment_template.edited", "class_kind.deleted"} <= trail


async def test_customer_care_is_refused_kinds_and_templates(app_client, world, api_key_factory):
    csrf = await as_(app_client, world, api_key_factory, "staff")
    assert (await app_client.get("/api/v1/class-kinds")).status_code == 403
    assert (await app_client.post("/api/v1/class-kinds", json={"name": "IELTS"}, headers=h(csrf))).status_code == 403
