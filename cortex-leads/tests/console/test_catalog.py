"""Dữ liệu: the price list screen's API and the importer behind it (and behind `cli import-catalog`)."""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from support import h, sign_in
from test_auth import as_

from cortex_leads.catalog.importer import MAX_ROWS, ImportRefused, import_catalog
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

B = "/api/v1/catalog"
HEAD = "code,name,category,price,unit,valid_until\n"
GOOD = HEAD + "KH01,Khoá IELTS,khoa_hoc,6500000,khoá,2026-12-31\nKH02,Giao tiếp A2,khoa_hoc,3600000,khoá,\n"


@pytest.fixture
async def owner(app_client, world, api_key_factory, owner_engine):
    async with owner_engine.begin() as c:  # the shared world comes with a catalog row; these tests count rows, so start from none
        await c.execute(text("delete from catalog_item"))
    _, key = await api_key_factory(world.t, "owner", None)
    return app_client, h(await sign_in(app_client, key))


async def _items(tenant_id, code=None):
    async with tenant_session(tenant_id) as s:
        q = select(m.CatalogItem).order_by(m.CatalogItem.code, m.CatalogItem.version)
        return (await s.execute(q.where(m.CatalogItem.code == code) if code else q)).scalars().all()


# --- the importer --------------------------------------------------------------------------------------
async def test_a_dry_run_says_what_would_happen_and_writes_nothing(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, GOOD, dry_run=True)
    assert (r.new, r.changed, r.unchanged, r.errors) == (2, 0, 0, []) and r.dry_run
    assert await _items(t.id) == []


async def test_a_changed_row_becomes_a_new_version_and_an_unchanged_one_is_left_alone(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        await import_catalog(s, t.id, GOOD)
    async with tenant_session(t.id) as s:
        again = await import_catalog(s, t.id, GOOD)
    assert (again.new, again.changed, again.unchanged) == (0, 0, 2)
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, GOOD.replace("6500000", "6900000"))
    assert (r.new, r.changed, r.unchanged) == (0, 1, 1)
    assert [(i.version, i.active, float(i.price)) for i in await _items(t.id, "KH01")] == [(1, False, 6500000.0), (2, True, 6900000.0)]


async def test_a_new_expiry_or_category_is_a_change_too_and_the_slot_details_are_carried_over(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        s.add(m.CatalogItem(tenant_id=t.id, code="HT1", name="Học thử", category="lich_hoc_thu", price=None, version=1, attrs={"suc_chua": 8}))
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, HEAD + "HT1,Học thử,lich_hoc_thu,,,2027-01-05\n")
    assert r.changed == 1
    new = (await _items(t.id, "HT1"))[-1]
    assert new.version == 2 and new.attrs == {"suc_chua": 8} and new.valid_until == datetime(2027, 1, 5, tzinfo=UTC)


@pytest.mark.parametrize("row,fragment", [
    ("KH9,Khoá,x,6,5 triệu,khoá,", "nhiều ô hơn"),
    ('KH9,Khoá,x,"6,5 triệu",khoá,', "không phải số"),
    ("KH9,Khoá,x,-5,khoá,", "không phải số"),
    ("KH9,Khoá,x,1e6,khoá,", "không phải số"),
    ("KH9,Khoá,x,100,khoá,31/12/2026", "không đúng dạng ngày"),
    (",Khoá,x,100,khoá,", "thiếu cột «code»"),
    ("KH9,,x,100,khoá,", "thiếu cột «name»"),
    ("KH9," + "a" * 201 + ",x,100,khoá,", "dài quá 200"),
])
async def test_a_bad_row_is_reported_with_its_line_and_skipped_while_the_good_ones_go_in(tenant_factory, row, fragment):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, HEAD + "OK1,Tốt,x,100,khoá,\n" + row + "\n")
    assert r.new == 1 and len(r.errors) == 1 and r.errors[0]["line"] == 3 and fragment in r.errors[0]["message"]
    assert [i.code for i in await _items(t.id)] == ["OK1"]


async def test_a_code_twice_in_one_file_is_reported_and_the_first_wins(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, HEAD + "A,Một,x,1,,\nA,Hai,x,2,,\n")
    assert r.new == 1 and "đã có ở dòng trên" in r.errors[0]["message"]
    assert [i.name for i in await _items(t.id)] == ["Một"]


async def test_a_file_that_cannot_be_used_at_all_is_refused_whole(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        for text, code in (("a,b\n1,2\n", "NO_HEADER"), ("", "NO_HEADER"), (HEAD + "A,Kh�oa,x,1,,\n", "NOT_UTF8"),
                           (HEAD + "A," + "x" * 1_100_000 + ",x,1,,\n", "TOO_BIG"), (HEAD + "A,B,x,1,,\n" * (MAX_ROWS + 1), "TOO_MANY_ROWS")):
            with pytest.raises(ImportRefused) as e:
                await import_catalog(s, t.id, text)
            assert e.value.code == code, text[:30]
    assert await _items(t.id) == []


async def test_a_byte_order_mark_and_spreadsheet_style_headers_are_fine_and_a_formula_looking_name_is_just_a_name(tenant_factory):
    t = await tenant_factory()
    async with tenant_session(t.id) as s:
        r = await import_catalog(s, t.id, "﻿ code , name ,category,price,unit,valid_until\nA,=HYPERLINK(\"http://x\"),@x,100,,\n")
    assert r.new == 1 and not r.errors
    assert (await _items(t.id))[0].name == '=HYPERLINK("http://x")'


# --- the API --------------------------------------------------------------------------------------------
async def test_the_list_shows_active_rows_with_their_state_and_the_stats(owner, world):
    client, _ = owner
    soon, past = datetime.now(UTC) + timedelta(days=5), datetime.now(UTC) - timedelta(days=1)
    async with tenant_session(world.t.id) as s:
        s.add_all([m.CatalogItem(tenant_id=world.t.id, code="A", name="Còn lâu", category="khoa_hoc", price=1500000, version=1),
                   m.CatalogItem(tenant_id=world.t.id, code="B", name="Sắp hết", category="khoa_hoc", price=None, version=1, valid_until=soon),
                   m.CatalogItem(tenant_id=world.t.id, code="C", name="Quá hạn", category="uu_dai", price=100, version=2, valid_until=past),
                   m.CatalogItem(tenant_id=world.t.id, code="C", name="Bản cũ", category="uu_dai", price=90, version=1, active=False)])
    r = (await client.get(B)).json()
    assert [(i["code"], i["state"], i["version"]) for i in r["items"]] == [("A", "ok", 1), ("B", "soon", 1), ("C", "expired", 2)]
    assert r["items"][0]["price"] == 1500000 and r["items"][1]["price"] is None and r["items"][2]["valid_until"].endswith("Z")
    assert r["stats"] == {"active": 3, "soon": 1, "expired": 1, "last_import_at": None} and r["categories"] == ["khoa_hoc", "uu_dai"] and r["can_import"] is True


async def test_import_checks_first_then_saves_and_the_audit_line_holds_counts_only(owner, world):
    client, hd = owner
    r = await client.post(f"{B}/import", json={"csv": GOOD, "dry_run": True}, headers=hd)
    assert r.status_code == 200 and r.json()["to_save"] == 2 and r.json()["dry_run"] is True
    assert await _items(world.t.id) == []
    r = await client.post(f"{B}/import", json={"csv": GOOD, "dry_run": False}, headers=hd)
    assert r.json()["new"] == 2 and r.json()["dry_run"] is False
    assert [i.code for i in await _items(world.t.id)] == ["KH01", "KH02"]
    async with tenant_session(world.t.id) as s:
        (ev,) = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "catalog.imported"))).scalars().all()
    assert ev.metadata_ == {"new": 2, "changed": 0, "unchanged": 0, "errors": 0} and "IELTS" not in ev.summary
    assert (await client.get(B)).json()["stats"]["last_import_at"] is not None


async def test_saving_must_be_asked_for_and_an_empty_save_leaves_no_audit_line(owner, world):
    client, hd = owner
    assert (await client.post(f"{B}/import", json={"csv": GOOD}, headers=hd)).json()["dry_run"] is True  # the default is the safe one
    assert await _items(world.t.id) == []
    await client.post(f"{B}/import", json={"csv": GOOD, "dry_run": False}, headers=hd)
    await client.post(f"{B}/import", json={"csv": GOOD, "dry_run": False}, headers=hd)  # nothing changed
    async with tenant_session(world.t.id) as s:
        assert len((await s.execute(select(m.AuditEvent).where(m.AuditEvent.action == "catalog.imported"))).scalars().all()) == 1


async def test_a_refused_file_answers_with_a_code_and_a_sentence(owner):
    client, hd = owner
    r = await client.post(f"{B}/import", json={"csv": "a,b\n1,2\n", "dry_run": False}, headers=hd)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "NO_HEADER" and "code,name" in r.json()["detail"]["message"]
    r = await client.post(f"{B}/import", json={"csv": HEAD + "A,x," + "y" * 1_100_000, "dry_run": False}, headers=hd)
    assert r.status_code == 422  # too long for the schema, never read


async def test_staff_may_read_and_download_the_template_but_not_import(app_client, world, api_key_factory, owner_engine):
    async with owner_engine.begin() as c:
        await c.execute(text("delete from catalog_item"))
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    assert (await app_client.get(B)).json()["can_import"] is False
    t = (await app_client.get(f"{B}/template")).json()
    assert t["filename"].endswith(".csv") and t["csv"].startswith("code,name,") and not any(line[:1] in "=+-@" for line in t["csv"].splitlines())
    r = await app_client.post(f"{B}/import", json={"csv": GOOD, "dry_run": False}, headers=h(csrf))
    assert r.status_code == 403 and r.json()["detail"]["code"] == "FORBIDDEN"
    assert await _items(world.t.id) == []


async def test_one_business_never_sees_or_changes_the_rows_of_another(owner, world, tenant_factory):
    client, hd = owner
    other = await tenant_factory(name="Khác")
    async with tenant_session(other.id) as s:
        s.add(m.CatalogItem(tenant_id=other.id, code="KH01", name="Của người khác", price=1, version=1))
    assert (await client.get(B)).json()["items"] == []
    r = await client.post(f"{B}/import", json={"csv": GOOD, "dry_run": False}, headers=hd)
    assert r.json()["new"] == 2  # KH01 is new here: the other business's row is not "the active one"
    assert [(i.name, i.version) for i in await _items(other.id)] == [("Của người khác", 1)]
    assert [(i.code, i.version) for i in await _items(world.t.id)] == [("KH01", 1), ("KH02", 1)]
