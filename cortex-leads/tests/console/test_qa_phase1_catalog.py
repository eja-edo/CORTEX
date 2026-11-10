"""QA (Agent B) for phase 1, the price list ("Dữ liệu"): who may call what, three-business isolation, hostile CSV files, what a dry run
may not touch, what versioning keeps, the audit line, and two imports at the same moment. Written without Agent A's own tests."""
import asyncio
import time

import pytest
from sqlalchemy import text
from support import h, sign_in
from test_auth import as_

from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

B = "/api/v1/catalog"
HEAD = "code,name,category,price,unit,valid_until\n"


@pytest.fixture
async def owner(app_client, world, api_key_factory, owner_engine):
    async with owner_engine.begin() as c:
        await c.execute(text("delete from catalog_item"))
    _, key = await api_key_factory(world.t, "owner", None)
    return app_client, h(await sign_in(app_client, key))


async def count(owner_engine, table="catalog_item", where="true"):
    async with owner_engine.connect() as c:
        return (await c.execute(text(f"select count(*) from {table} where {where}"))).scalar_one()


async def post(client, hd, csv_text, dry=False):
    return await client.post(f"{B}/import", json={"csv": csv_text, "dry_run": dry}, headers=hd)


# --- who may call what -----------------------------------------------------------------------------------
async def test_nobody_signed_out_reads_or_imports(app_client, world):
    app_client.cookies.clear()
    assert (await app_client.get(B)).status_code == 401
    assert (await app_client.get(f"{B}/template")).status_code == 401
    assert (await app_client.post(f"{B}/import", json={"csv": HEAD, "dry_run": False})).status_code in (401, 403)


async def test_an_import_without_the_csrf_token_is_refused_and_writes_nothing(owner, owner_engine):
    client, _ = owner
    r = await client.post(f"{B}/import", json={"csv": HEAD + "A,B,x,1,,\n", "dry_run": False})
    assert r.status_code == 403 and await count(owner_engine) == 0
    r = await client.post(f"{B}/import", json={"csv": HEAD + "A,B,x,1,,\n", "dry_run": False}, headers={"X-CSRF-Token": "wrong"})
    assert r.status_code == 403 and await count(owner_engine) == 0


async def test_staff_cannot_import_even_a_dry_run_and_cannot_pass_a_role_in_the_body(app_client, world, api_key_factory, owner_engine):
    async with owner_engine.begin() as c:
        await c.execute(text("delete from catalog_item"))
    csrf, _ = await as_(app_client, world, api_key_factory, "staff", "nv1")
    for dry in (True, False):
        r = await app_client.post(f"{B}/import", json={"csv": HEAD + "A,B,x,1,,\n", "dry_run": dry, "role": "owner"}, headers=h(csrf))
        assert r.status_code == 403
    assert await count(owner_engine) == 0


# --- isolation (A1) and the tenant from the session (A3) ---------------------------------------------------
async def test_catalog_item_has_forced_row_security(owner_engine):
    async with owner_engine.connect() as c:
        row = (await c.execute(text("select relrowsecurity, relforcerowsecurity from pg_class where relname = 'catalog_item'"))).one()
    assert tuple(row) == (True, True)


async def test_three_businesses_and_a_tenant_id_in_the_body_changes_nothing(owner, world, tenant_factory, owner_engine):
    client, hd = owner
    b, c = await tenant_factory("Beta"), await tenant_factory("Gamma")
    for t, name in ((b, "Của Beta"), (c, "Của Gamma")):
        async with tenant_session(t.id) as s:
            s.add(m.CatalogItem(tenant_id=t.id, code="KH01", name=name, price=1, version=1))
    r = await client.post(f"{B}/import", json={"csv": HEAD + "KH01,Của A,x,5,,\nKH02,Hai,x,6,,\n", "dry_run": False,
                                               "tenant_id": str(b.id), "tenant": str(c.id)}, headers=hd)
    assert r.status_code == 200 and r.json()["new"] == 2
    async with owner_engine.connect() as cn:
        got = (await cn.execute(text("select tenant_id::text, code, name, version, active from catalog_item order by tenant_id, code"))).all()
    mine = [g for g in got if g[0] == str(world.t.id)]
    assert sorted((g[1], g[2]) for g in mine) == [("KH01", "Của A"), ("KH02", "Hai")]
    assert [(g[2], g[3], g[4]) for g in got if g[0] == str(b.id)] == [("Của Beta", 1, True)]
    assert [(g[2], g[3], g[4]) for g in got if g[0] == str(c.id)] == [("Của Gamma", 1, True)]
    assert [i["name"] for i in (await client.get(B)).json()["items"]] == ["Của A", "Hai"]


# --- hostile files -----------------------------------------------------------------------------------------
async def test_a_dry_run_writes_nothing_anywhere(owner, owner_engine):
    client, hd = owner
    before = (await count(owner_engine), await count(owner_engine, "audit_event"))
    r = await post(client, hd, HEAD + "A,Một,x,1,,\nB,Hai,x,2,,\nbad,,,,,\n", dry=True)
    assert r.status_code == 200 and r.json()["to_save"] == 2 and len(r.json()["errors"]) == 1
    assert (await count(owner_engine), await count(owner_engine, "audit_event")) == before


HOSTILE = [
    ("huge field under 1MB", HEAD + "A," + "x" * 200_000 + ",x,1,,\n"),
    ("far future with offset", HEAD + "A,B,x,1,,9999-12-31T23:59:59+07:00\n"),
    ("far past with offset", HEAD + "A,B,x,1,,0001-01-01T00:00:00+07:00\n"),
    ("year 9999 date", HEAD + "A,B,x,1,,9999-12-31\n"),
    ("nul byte in a name", HEAD + "A,B\x00C,x,1,,\n"),
    ("nan price", HEAD + "A,B,x,NaN,,\n"),
    ("infinity price", HEAD + "A,B,x,Infinity,,\n"),
    ("1e999 price", HEAD + "A,B,x,1e999,,\n"),
    ("17 digit price", HEAD + "A,B,x,99999999999999999,,\n"),
    ("3 decimals", HEAD + "A,B,x,1.001,,\n"),
    ("arabic-indic digits", HEAD + "A,B,x,٣٤٥,,\n"),
    ("fullwidth digits", HEAD + "A,B,x,１２３,,\n"),
    ("negative", HEAD + "A,B,x,-1,,\n"),
    ("month 13", HEAD + "A,B,x,1,,2026-13-45\n"),
    ("hour 25", HEAD + "A,B,x,1,,2026-12-31T25:00\n"),
    ("quote never closed", HEAD + 'A,"B,x,1,,\n'),
    ("lone carriage return", HEAD + "A,B,x,1,,\rC,D,x,2,,\r"),
    ("sql-looking", HEAD + "A,\"x'); DROP TABLE catalog_item;--\",x,1,,\n"),
    ("utf16 read as text", (HEAD + "A,B,x,1,,\n").encode("utf-16").decode("latin-1")),
    ("header only", HEAD),
    ("empty", ""),
    ("blank lines only", "\n\n\n"),
    ("headers swapped", "name,code,price,category,unit,valid_until\nTên,MA,5,x,,\n"),
    ("extra header column", HEAD.strip() + ",notes\nA,B,x,1,,,hello\n"),
    ("missing header column", "code,name\nA,B\n"),
    ("duplicate header", "code,code,name\nA,B,C\n"),
]


@pytest.mark.parametrize("label,body", HOSTILE, ids=[x[0] for x in HOSTILE])
async def test_a_hostile_file_gets_a_clean_answer_never_a_crash(owner, owner_engine, label, body):
    client, hd = owner
    try:
        r = await post(client, hd, body)
    except Exception as e:  # noqa: BLE001  the test client re-raises a server error
        pytest.fail(f"{label}: the server crashed with {type(e).__name__}: {str(e)[:120]}")
    assert r.status_code in (200, 422), f"{label}: {r.status_code} {r.text[:200]}"
    assert r.status_code != 500
    if r.status_code == 200:
        j = r.json()
        assert j["new"] + j["changed"] == await count(owner_engine), label


async def test_what_the_odd_values_that_do_get_in_look_like(owner, owner_engine):
    """Records what is stored for the values the file is allowed to carry (a note for the report, with real assertions where one is clear)."""
    client, hd = owner
    csv_text = (HEAD + 'F1,"=HYPERLINK(""http://evil"")",@a,100,,\nF2,+cmd|\' /C calc\'!A0,-x,200,,\nF3,"x\'); DROP TABLE catalog_item;--",y,300,,\n')
    r = await post(client, hd, csv_text)
    assert r.json()["new"] == 3 and not r.json()["errors"]
    async with owner_engine.connect() as cn:
        names = {x[0]: x[1] for x in (await cn.execute(text("select code, name from catalog_item"))).all()}
    assert names["F1"].startswith("=") and names["F3"].endswith("--") and await count(owner_engine) == 3
    items = (await client.get(B)).json()["items"]
    assert {i["code"] for i in items} == {"F1", "F2", "F3"}
    tmpl = (await client.get(f"{B}/template")).json()["csv"]
    assert not any(line[:1] in "=+-@" for line in tmpl.splitlines())


async def test_the_edges_of_the_limits(owner, owner_engine):
    client, hd = owner
    row = "A{:05d},Tên,x,1,,\n"
    ok = HEAD + "".join(row.format(i) for i in range(2000))
    r = await post(client, hd, ok, dry=True)
    assert r.status_code == 200 and r.json()["new"] == 2000
    r = await post(client, hd, HEAD + "".join(row.format(i) for i in range(2001)), dry=True)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "TOO_MANY_ROWS"
    t0 = time.perf_counter()
    r = await post(client, hd, HEAD + "A,B,x,1,,\n" * 100_000, dry=True)
    assert r.status_code == 422 and time.perf_counter() - t0 < 5
    r = await post(client, hd, "﻿" + HEAD + "A,B,x,1,,\n")
    assert r.status_code == 200 and r.json()["new"] == 1
    cp = "A,Khoá học tiếng Anh,x,1,,\n".encode("cp1258", errors="replace").decode("utf-8", errors="replace")
    r = await post(client, hd, HEAD + cp, dry=True)
    assert r.status_code in (200, 422)


async def test_a_code_with_spaces_and_a_very_long_code_and_name(owner, owner_engine):
    client, hd = owner
    r = await post(client, hd, HEAD + "  KH01  ,  Tên  ,x,1,,\n" + "C" * 65 + ",Tên,x,1,,\nD,"+ "n" * 201 + ",x,1,,\n")
    j = r.json()
    assert j["new"] == 1 and len(j["errors"]) == 2
    async with owner_engine.connect() as cn:
        assert (await cn.execute(text("select code, name from catalog_item"))).all() == [("KH01", "Tên")]


# --- what versioning keeps -----------------------------------------------------------------------------------
async def test_same_file_twice_is_zero_change_a_changed_price_is_a_new_version_and_an_absent_code_stays(owner, world, owner_engine):
    client, hd = owner
    async with tenant_session(world.t.id) as s:
        s.add(m.CatalogItem(tenant_id=world.t.id, code="HT1", name="Học thử", category="lich_hoc_thu", version=1, attrs={"suc_chua": 8}))
    two = HEAD + "A,Một,x,100,,\nB,Hai,x,200,,\n"
    assert (await post(client, hd, two)).json()["new"] == 2
    again = (await post(client, hd, two)).json()
    assert (again["new"], again["changed"], again["unchanged"], again["to_save"]) == (0, 0, 2, 0)
    r = (await post(client, hd, HEAD + "A,Một,x,150,,\n")).json()  # B and HT1 are absent from this file
    assert (r["new"], r["changed"]) == (0, 1)
    async with owner_engine.connect() as cn:
        got = (await cn.execute(text("select code, version, active, price from catalog_item order by code, version"))).all()
    assert [(c, v, a) for c, v, a, _ in got] == [("A", 1, False), ("A", 2, True), ("B", 1, True), ("HT1", 1, True)]
    r = (await post(client, hd, HEAD + "HT1,Học thử,lich_hoc_thu,,,2031-01-01\n")).json()
    assert r["changed"] == 1
    async with owner_engine.connect() as cn:
        att = (await cn.execute(text("select attrs->>'suc_chua', active from catalog_item where code='HT1' order by version"))).all()
    assert att == [("8", False), ("8", True)]


async def test_the_audit_line_holds_counts_and_none_of_the_rows(owner, owner_engine):
    client, hd = owner
    await post(client, hd, HEAD + "A,Nguyễn Văn An 0901234567,x,100,,\n")
    async with owner_engine.connect() as cn:
        ev = (await cn.execute(text("select summary, metadata::text from audit_event where action = 'catalog.imported'"))).all()
    assert len(ev) == 1 and "0901234567" not in ev[0][0] + ev[0][1] and "Nguyễn" not in ev[0][0] + ev[0][1]
    assert await count(owner_engine, "audit_event", "(summary || metadata::text) ilike '%0901234567%'") == 0


async def test_two_imports_of_the_same_code_at_the_same_moment(owner, world, owner_engine):
    """Whatever the outcome it must be an answer, never a crash, and the catalog must stay sane (one active row per code)."""
    client, hd = owner
    await post(client, hd, HEAD + "A,Một,x,100,,\n")
    outcomes = await asyncio.gather(post(client, hd, HEAD + "A,Một,x,111,,\n"), post(client, hd, HEAD + "A,Một,x,222,,\n"), return_exceptions=True)
    shown = [type(o).__name__ if isinstance(o, Exception) else o.status_code for o in outcomes]
    async with owner_engine.connect() as cn:
        active = (await cn.execute(text("select count(*) from catalog_item where code = 'A' and active"))).scalar_one()
        dup = (await cn.execute(text("select count(*) from (select version from catalog_item where code='A' group by version having count(*)>1) t"))).scalar_one()
    assert active == 1 and dup == 0, shown
    crashed = [s for s in shown if not isinstance(s, int) or s >= 500]
    assert not crashed, f"concurrent import answered {shown}"


@pytest.mark.parametrize("price", ["٣٤٥", "１２３"])
async def test_only_plain_digits_are_a_price(owner, owner_engine, price):
    """R157: Arabic-Indic and full-width digits are digits to `\\d`, but the screen says "plain numbers only"."""
    client, hd = owner
    r = await post(client, hd, HEAD + f"A,B,x,{price},,\n")
    assert r.status_code == 200 and r.json()["new"] == 0 and len(r.json()["errors"]) == 1


@pytest.mark.parametrize("body", [HEAD + "A," + "x" * 200_000 + ",x,1,,\n", HEAD + "A,B,x,1,,\rC,D,x,2,,\r"])
async def test_a_file_the_csv_reader_cannot_parse_is_refused_in_words(owner, body):
    """R154/R155: a huge cell or a lone carriage return (Excel's "CSV (Macintosh)") was an uncaught csv.Error, so a 500."""
    client, hd = owner
    r = await post(client, hd, body)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "BAD_CSV" and "CSV UTF-8" in r.json()["detail"]["message"]
