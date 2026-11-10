"""Which classes a person may touch (WP46). A role without `classes.all` holds its class permissions for the classes it was given and no
others, and that is decided here, once, for all of the console:

- An endpoint whose address points at something of a class says so: `need_class("perm")` finds the class behind `{class_id}`, `{assignment_id}`,
  `{draft_id}`, `{item_id}` or `{lesson_id}` before the handler runs.
- An endpoint that lists, or that is told the class in its body, keeps `need("perm")` and narrows itself with `my_classes` / `ensure_class`.

`tests/console/test_teacher.py` fails on an endpoint that uses a class permission and has said neither. What is out of reach answers exactly like
what does not exist, so a teacher cannot tell another class's id from a wrong one; the attempt is a line in the activity log."""
from typing import Any
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select

from cortex_leads.auth.perms import Perm
from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit_new
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

ALL = Perm.CLASSES_ALL


async def my_classes(s: Any, sess: Session) -> set[UUID] | None:
    """The classes this person is limited to; None: every class of the business."""
    if sess.can(ALL):
        return None
    return set((await s.execute(select(m.ClassTeacher.class_id).where(m.ClassTeacher.user_id == sess.user_id))).scalars())


async def _refuse(sess: Session, where: str) -> HTTPException:
    await audit_new(sess, "access", "permission.refused", "Thử mở thứ của một lớp không phụ trách", result="denied", metadata={"path": where})
    return HTTPException(404, {"code": "NOT_FOUND", "message": "Không tìm thấy mục này"})


async def ensure_class(s: Any, sess: Session, class_id: UUID) -> None:
    """For a class named in a request body. Call before anything is written in `s`: the refusal is logged in a transaction of its own."""
    mine = await my_classes(s, sess)
    if mine is not None and class_id not in mine:
        raise await _refuse(sess, f"class:{class_id}")


async def _class_behind(s: Any, params: dict[str, str]) -> UUID | None:
    """The class of what the address names. None: it names nothing that exists."""
    try:
        ids = {k: UUID(v) for k, v in params.items()}
    except ValueError:  # not an id at all: the framework turns that down for everyone, this only must not fall over first
        return None
    if "class_id" in ids:
        return ids["class_id"]
    if "lesson_id" in ids:
        q = select(m.Lesson.class_id).where(m.Lesson.id == ids["lesson_id"])
    elif "item_id" in ids:
        q = select(m.Assignment.class_id).join(m.GradeItem, m.GradeItem.assignment_id == m.Assignment.id).where(m.GradeItem.id == ids["item_id"])
    elif "assignment_id" in ids or "draft_id" in ids:
        q = select(m.Assignment.class_id).where(m.Assignment.id == (ids.get("assignment_id") or ids["draft_id"]))
    else:
        raise RuntimeError(f"need_class on an address that names no class: {sorted(params)}")
    return (await s.execute(q)).scalar_one_or_none()


def need_class(perm: str):  # type: ignore[no-untyped-def]
    """`need(perm)`, and what the address points at must belong to one of this person's classes."""
    allowed = need(perm).dependency

    async def dep(request: Request, sess: Session = Depends(allowed)) -> Session:
        if sess.can(ALL):
            return sess
        async with tenant_session(sess.caller.tenant_id) as s:
            class_id = await _class_behind(s, dict(request.path_params))
            mine = await my_classes(s, sess)
        if class_id is None or class_id not in (mine or set()):
            raise await _refuse(sess, request.url.path)
        return sess

    dep.class_scoped = True  # type: ignore[attr-defined]  # read by the test that holds every class endpoint to a decision
    return Depends(dep)
