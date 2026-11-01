"""WP38: 0037 turns lesson_source + classroom_source (and their guides, drafts, submissions) into classes and assignments without losing a row
or sending anything twice; 0038 then drops the old tables. Runs on a scratch database it makes and drops, from revision 0036 with data in the
old shape, because the point is what the migration does to rows that already exist."""
import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from cortex_leads.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
SCRATCH = "cortex_leads_migtest"
CRITERIA = json.dumps([{"id": "thi", "label": "Đúng thì", "points": 10, "descriptor": ""}])


def run(url: str, *statements: tuple[str, dict]) -> list:
    async def go() -> list:
        engine = create_async_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
        out: list = []
        try:
            async with engine.connect() as c:
                for sql, params in statements:
                    out.append((await c.execute(text(sql), params)).fetchall() if sql.lstrip().lower().startswith("select") else await c.execute(text(sql), params))
        finally:
            await engine.dispose()
        return out
    return asyncio.run(go())


@pytest.fixture
def scratch(monkeypatch):
    owner = get_settings().DATABASE_OWNER_URL
    base = owner.rsplit("/", 1)[0]
    run(f"{base}/postgres", (f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)", {}), (f"CREATE DATABASE {SCRATCH}", {}))
    url = f"{base}/{SCRATCH}"
    monkeypatch.setenv("CL_DATABASE_OWNER_URL", url)
    get_settings.cache_clear()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    yield url, cfg
    get_settings.cache_clear()
    run(f"{base}/postgres", (f"DROP DATABASE IF EXISTS {SCRATCH} WITH (FORCE)", {}))


def test_old_sources_become_classes_and_their_work_becomes_assignments(scratch):
    url, cfg = scratch
    command.upgrade(cfg, "0036")
    t, rec, gra, acct = (str(uuid4()) for _ in range(4))
    ls1, ls2, cs1, cs2 = (str(uuid4()) for _ in range(4))
    l_done, l_new, guide1, gi1, gi2, d_made, d_open = (str(uuid4()) for _ in range(7))
    run(url,
        ("INSERT INTO tenant (id, name) VALUES (:t, 'T')", {"t": t}),
        ("INSERT INTO sandbox (id, tenant_id, name, profile_ref, purpose) VALUES (:s, :t, 'recap', 'lesson_recapper@1', 'lesson_recap')", {"s": rec, "t": t}),
        ("INSERT INTO sandbox (id, tenant_id, name, profile_ref, purpose) VALUES (:s, :t, 'grader', 'classroom_grader@1', 'classroom_grader')", {"s": gra, "t": t}),
        ("INSERT INTO google_account (id, tenant_id, label, secret_enc, connected_by) VALUES (:a, :t, 'Cô Lan', 'x', 'owner')", {"a": acct, "t": t}),
        # a class with a Drive folder, posting to course C1 as a published announcement
        ("""INSERT INTO lesson_source (id, tenant_id, sandbox_id, kind, ref, label, google_account_id, owned, classroom_course_id, classroom_course_name, classroom_publish)
            VALUES (:i, :t, :s, 'drive', 'F1', 'Lớp A', :a, true, 'C1', 'IELTS A', true)""", {"i": ls1, "t": t, "s": rec, "a": acct}),
        # a source made on the command line: not a class the console ever listed
        ("INSERT INTO lesson_source (id, tenant_id, sandbox_id, kind, ref) VALUES (:i, :t, :s, 'local', '/x')", {"i": ls2, "t": t, "s": rec}),
        ("INSERT INTO classroom_source (id, tenant_id, sandbox_id, course_id, auth_kind, google_account_id) VALUES (:i, :t, :s, 'C1', 'oauth', :a)", {"i": cs1, "t": t, "s": gra, "a": acct}),
        ("INSERT INTO classroom_source (id, tenant_id, sandbox_id, course_id, auth_kind, label) VALUES (:i, :t, :s, 'C2', 'oauth', 'Lớp chấm')", {"i": cs2, "t": t, "s": gra}),
        ("INSERT INTO lesson (id, tenant_id, sandbox_id, source_id, file_id, name, status, recap, finished_at) VALUES (:i, :t, :s, :c, 'f1', 'xong', 'done', '{}', now())", {"i": l_done, "t": t, "s": rec, "c": ls1}),
        ("INSERT INTO lesson (id, tenant_id, sandbox_id, source_id, file_id, name, status) VALUES (:i, :t, :s, :c, 'f2', 'mới', 'queued')", {"i": l_new, "t": t, "s": rec, "c": ls1}),
        ("INSERT INTO grading_guide (id, tenant_id, sandbox_id, source_id, coursework_id, title, max_points, criteria) VALUES (:i, :t, :s, :c, 'cw1', 'Bài 1', 10, CAST(:k AS jsonb))",
         {"i": guide1, "t": t, "s": gra, "c": cs1, "k": CRITERIA}),
        ("""INSERT INTO assignment_draft (id, tenant_id, sandbox_id, source_id, title, description, max_points, criteria, origin, status, coursework_id)
            VALUES (:i, :t, :s, :c, 'Bài 1', 'Mô tả bài một', 10, CAST(:k AS jsonb), 'ai', 'created', 'cw1')""", {"i": d_made, "t": t, "s": gra, "c": cs1, "k": CRITERIA}),
        ("""INSERT INTO assignment_draft (id, tenant_id, sandbox_id, source_id, title, description, max_points, criteria, origin, status)
            VALUES (:i, :t, :s, :c, 'Bài chưa tạo', 'Mô tả bài nháp', 5, CAST(:k AS jsonb), 'teacher', 'draft')""", {"i": d_open, "t": t, "s": gra, "c": cs1, "k": CRITERIA}),
        ("""INSERT INTO grade_item (id, tenant_id, sandbox_id, source_id, coursework_id, submission_id, student_ref, work_title, ours, status)
            VALUES (:i, :t, :s, :c, 'cw1', 'sub1', 'u1', 'Bài 1', true, 'proposed')""", {"i": gi1, "t": t, "s": gra, "c": cs1}),
        ("""INSERT INTO grade_item (id, tenant_id, sandbox_id, source_id, coursework_id, submission_id, student_ref, work_title, ours, status)
            VALUES (:i, :t, :s, :c, 'cw2', 'sub2', 'u2', 'Bài viết tay', false, 'skipped')""", {"i": gi2, "t": t, "s": gra, "c": cs1}))

    command.upgrade(cfg, "0037")

    classes, assignments, items, lessons = run(
        url,
        ("SELECT id, name, listed, recap_sandbox_id, grader_sandbox_id, course_id, classroom_account_id, drive_account_id, recap_mode, grading_mode FROM class ORDER BY name", {}),
        ("SELECT class_id, coursework_id, origin, authored_by, state, title, criteria IS NOT NULL FROM assignment", {}),
        ("SELECT id, assignment_id FROM grade_item", {}),
        ("SELECT id, class_id, released_at, released_by FROM lesson", {}))

    by_name = {c[1]: c for c in classes}
    assert set(by_name) == {"Lớp A", "/x", "Lớp chấm"}  # three classes from four sources: the course C1 is one class, not two
    a = by_name["Lớp A"]
    assert str(a[0]) == ls1 and a[2] is True and (str(a[3]), str(a[4])) == (rec, gra) and a[5] == "C1"  # recordings AND grading in one class
    assert (str(a[6]), str(a[7])) == (acct, acct) and (a[8], a[9]) == ("review", "review")  # the careful policy, whatever the old behaviour was
    assert by_name["/x"][2] is False  # kept because lessons point at it, not listed as a class
    assert by_name["Lớp chấm"][2] is True and by_name["Lớp chấm"][3] is None and str(by_name["Lớp chấm"][4]) == gra  # a course that only grades

    works = {(w[1], w[5]): w for w in assignments}
    assert len(works) == 3
    made = works[("cw1", "Bài 1")]
    assert (made[2], made[3], made[4], made[6]) == ("app", "ai", "created", True)  # the guide and the approved draft are one assignment
    by_hand = works[("cw2", "Bài viết tay")]
    assert (by_hand[2], by_hand[6]) == ("classroom", False)  # seen only through its submissions: nothing to grade by
    draft = works[(None, "Bài chưa tạo")]
    assert (draft[2], draft[3], draft[4]) == ("app", "teacher", "draft")

    titles = {str(i[0]): next(w[5] for w in assignments if w[0] and (w[1] == ("cw1" if str(i[0]) == gi1 else "cw2"))) for i in items}
    assert titles == {gi1: "Bài 1", gi2: "Bài viết tay"} and all(i[1] is not None for i in items)

    got = {str(x[0]): x for x in lessons}
    assert str(got[l_done][1]) == ls1 and got[l_done][2] is not None and got[l_done][3] == "migration"  # a recap already sent is not sent again
    assert got[l_new][2] is None  # one still being made waits for the class's mode

    command.upgrade(cfg, "head")
    gone = run(url, ("SELECT to_regclass('lesson_source'), to_regclass('classroom_source'), to_regclass('grading_guide'), to_regclass('assignment_draft')", {}),
               ("SELECT count(*) FROM class", {}), ("SELECT count(*) FROM assignment", {}))
    assert gone[0][0] == (None, None, None, None) and gone[1][0][0] == 3 and gone[2][0][0] == 3
