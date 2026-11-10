"""Class kinds and their assignment templates: a business names its kinds of class, each kind keeps ready-made assignments, and the compose
form can be filled from one. A template is only a set of values for the form (all optional); it is checked as a whole when the form is saved,
by the same code that checks any assignment. A kind and its templates are the business's own: whoever grades reads them (`grading.use`), and a teacher, who runs only their own classes, does not change them (`templates.manage`)."""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select

from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.core.ids import uuid7
from cortex_leads.core.timefmt import wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.grader import assignments
from cortex_leads.grader.guide import Criterion

router = APIRouter()
MAX_KINDS = 50
MAX_TEMPLATES = 200  # per kind


def _kind_404() -> HTTPException:
    return HTTPException(404, {"code": "NOT_FOUND", "message": "Không có loại lớp này"})


def _name_taken() -> HTTPException:
    return HTTPException(409, {"code": "NAME_TAKEN", "message": "Tên này đã có rồi"})


def _item(t: m.AssignmentTemplate) -> dict[str, Any]:
    return {"id": str(t.id), "kind_id": str(t.kind_id), "name": t.name, "title": t.title, "description": t.description, "max_points": t.max_points,
            "criteria": t.criteria or [], "answer_key": t.answer_key, "check_prompt": t.check_prompt, "language": t.language,
            "topic_name": t.topic_name, "materials": t.materials, "created_by": t.created_by, "created_at": wire(t.created_at)}


class KindIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)


@router.get("/class-kinds")
async def list_kinds(sess: Session = need("grading.use")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        templates = dict((await s.execute(select(m.AssignmentTemplate.kind_id, func.count()).group_by(m.AssignmentTemplate.kind_id))).all())
        kinds = (await s.execute(select(m.ClassKind).order_by(m.ClassKind.name))).scalars().all()
        return {"items": [{"id": str(k.id), "name": k.name, "templates": templates.get(k.id, 0)} for k in kinds]}


@router.post("/class-kinds", status_code=201)
async def create_kind(body: KindIn, sess: Session = need("templates.manage")) -> dict[str, Any]:
    name = body.name.strip()
    async with tenant_session(sess.caller.tenant_id) as s:
        if (await s.scalar(select(func.count()).select_from(m.ClassKind))) >= MAX_KINDS:
            raise HTTPException(409, {"code": "TOO_MANY", "message": f"Tối đa {MAX_KINDS} loại lớp"})
        if (await s.execute(select(m.ClassKind.id).where(m.ClassKind.name == name))).first():
            raise _name_taken()
        k = m.ClassKind(id=uuid7(), tenant_id=sess.caller.tenant_id, name=name)
        s.add(k)
        await s.flush()
        await audit(sess, s, "config", "class_kind.created", f"Thêm loại lớp «{name}»", obj=("class_kind", str(k.id), name))
        return {"id": str(k.id), "name": name, "templates": 0}


@router.patch("/class-kinds/{kind_id}")
async def rename_kind(kind_id: UUID, body: KindIn, sess: Session = need("templates.manage")) -> dict[str, Any]:
    name = body.name.strip()
    async with tenant_session(sess.caller.tenant_id) as s:
        k = await s.get(m.ClassKind, kind_id)
        if k is None:
            raise _kind_404()
        if (await s.execute(select(m.ClassKind.id).where(m.ClassKind.name == name, m.ClassKind.id != k.id))).first():
            raise _name_taken()
        old, k.name = k.name, name
        await audit(sess, s, "config", "class_kind.renamed", f"Đổi tên loại lớp «{old}» thành «{name}»", obj=("class_kind", str(k.id), name))
        return {"id": str(k.id), "name": name}


@router.delete("/class-kinds/{kind_id}")
async def delete_kind(kind_id: UUID, sess: Session = need("templates.manage")) -> dict[str, Any]:
    """Takes the kind and its templates away; assignments already made from them are untouched."""
    async with tenant_session(sess.caller.tenant_id) as s:
        k = await s.get(m.ClassKind, kind_id)
        if k is None:
            raise _kind_404()
        name = k.name
        gone = (await s.execute(delete(m.AssignmentTemplate).where(m.AssignmentTemplate.kind_id == k.id))).rowcount
        await s.delete(k)
        await audit(sess, s, "config", "class_kind.deleted", f"Xoá loại lớp «{name}»", obj=("class_kind", str(kind_id), name),
                    metadata={"templates": gone})
        return {"deleted": str(kind_id), "templates": gone}


class TemplateIn(BaseModel):
    """Every field but the name is optional: a template can hold just a rubric, or just a brief."""
    name: str = Field(min_length=2, max_length=80)
    title: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=6000)
    max_points: int | None = Field(default=None, ge=1, le=100)
    criteria: list[Criterion] | None = Field(default=None, max_length=12)
    answer_key: str | None = Field(default=None, max_length=8000)
    check_prompt: str | None = Field(default=None, max_length=4000)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2}$")
    topic_name: str | None = Field(default=None, max_length=100)
    materials: list[assignments.MaterialIn] = Field(default_factory=list, max_length=assignments.MAX_MATERIALS)

    @model_validator(mode="after")
    def _rubric_adds_up(self) -> "TemplateIn":
        if self.criteria and self.max_points is not None and abs(sum(c.points for c in self.criteria) - self.max_points) > 0.01:
            raise ValueError("thang điểm cộng lại phải bằng tổng điểm")
        if self.criteria and len({c.id for c in self.criteria}) != len(self.criteria):
            raise ValueError("mã tiêu chí bị trùng")
        return self


def _values(body: TemplateIn) -> dict[str, Any]:
    try:
        for x in body.materials:
            assignments.to_material(x)  # the same check a posted assignment gets, so a bad link is refused here and not at posting time
    except ValueError as e:
        raise HTTPException(422, {"code": "BAD_MATERIAL", "message": f"Tệp đính kèm chưa đúng: {e}"}) from None
    blank = lambda v: (v.strip() or None) if isinstance(v, str) else v
    return {"name": body.name.strip(), "title": blank(body.title), "description": blank(body.description), "max_points": body.max_points,
            "criteria": [c.model_dump() for c in body.criteria] if body.criteria else None, "answer_key": blank(body.answer_key),
            "check_prompt": blank(body.check_prompt), "language": body.language, "topic_name": blank(body.topic_name),
            "materials": [{"url": x.url.strip(), "title": x.title.strip(), "share": x.share} for x in body.materials]}


@router.get("/class-kinds/{kind_id}/templates")
async def kind_templates(kind_id: UUID, sess: Session = need("grading.use")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        k = await s.get(m.ClassKind, kind_id)
        if k is None:
            raise _kind_404()
        rows = (await s.execute(select(m.AssignmentTemplate).where(m.AssignmentTemplate.kind_id == k.id).order_by(m.AssignmentTemplate.name))).scalars()
        return {"kind": {"id": str(k.id), "name": k.name}, "items": [_item(t) for t in rows]}


@router.post("/class-kinds/{kind_id}/templates", status_code=201)
async def create_template(kind_id: UUID, body: TemplateIn, sess: Session = need("templates.manage")) -> dict[str, Any]:
    vals = _values(body)
    async with tenant_session(sess.caller.tenant_id) as s:
        k = await s.get(m.ClassKind, kind_id)
        if k is None:
            raise _kind_404()
        if (await s.scalar(select(func.count()).select_from(m.AssignmentTemplate).where(m.AssignmentTemplate.kind_id == k.id))) >= MAX_TEMPLATES:
            raise HTTPException(409, {"code": "TOO_MANY", "message": f"Mỗi loại lớp tối đa {MAX_TEMPLATES} bài tập mẫu"})
        if (await s.execute(select(m.AssignmentTemplate.id).where(m.AssignmentTemplate.kind_id == k.id, m.AssignmentTemplate.name == vals["name"]))).first():
            raise _name_taken()
        t = m.AssignmentTemplate(id=uuid7(), tenant_id=sess.caller.tenant_id, kind_id=k.id, created_by=sess.actor, **vals)
        s.add(t)
        await s.flush()
        await audit(sess, s, "config", "assignment_template.created", f"Thêm bài tập mẫu «{t.name}» cho loại lớp «{k.name}»", obj=("assignment_template", str(t.id), t.name))
        return _item(t)


@router.put("/assignment-templates/{template_id}")
async def replace_template(template_id: UUID, body: TemplateIn, sess: Session = need("templates.manage")) -> dict[str, Any]:
    """The form sends the whole template, so a field left empty is cleared."""
    vals = _values(body)
    async with tenant_session(sess.caller.tenant_id) as s:
        t = await s.get(m.AssignmentTemplate, template_id)
        if t is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có bài tập mẫu này"})
        if (await s.execute(select(m.AssignmentTemplate.id).where(m.AssignmentTemplate.kind_id == t.kind_id, m.AssignmentTemplate.name == vals["name"],
                                                                 m.AssignmentTemplate.id != t.id))).first():
            raise _name_taken()
        for k, v in vals.items():
            setattr(t, k, v)
        await audit(sess, s, "config", "assignment_template.edited", f"Sửa bài tập mẫu «{t.name}»", obj=("assignment_template", str(t.id), t.name))
        return _item(t)


@router.delete("/assignment-templates/{template_id}")
async def delete_template(template_id: UUID, sess: Session = need("templates.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        t = await s.get(m.AssignmentTemplate, template_id)
        if t is None:
            raise HTTPException(404, {"code": "NOT_FOUND", "message": "Không có bài tập mẫu này"})
        name = t.name
        await s.delete(t)
        await audit(sess, s, "config", "assignment_template.deleted", f"Xoá bài tập mẫu «{name}»", obj=("assignment_template", str(template_id), name))
        return {"deleted": str(template_id)}
