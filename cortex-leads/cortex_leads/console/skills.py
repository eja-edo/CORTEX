"""Kỹ năng (WP27): list, detail with the trial, create from a form, and the draft -> trial -> live moves. Every move is
the function the old page already used (`forms.*`, `registry.*`); the console adds nothing the rules do not already allow."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cortex_leads.audit.service import diff
from cortex_leads.auth.perms import Perm
from cortex_leads.console.auth import Session, need
from cortex_leads.console.sandboxes import label_of
from cortex_leads.console.trail import VIEW_ONCE, audit
from cortex_leads.core.timefmt import vi_duration, wire
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.domain.pack import load_pack
from cortex_leads.skills.forms import (
    MIN_SHADOW_RUNS,
    PREFIX,
    TEMPLATES,
    FormSpec,
    build,
    go_live,
    preview,
    save_draft,
    start_trial,
    update_in_place,
)
from cortex_leads.skills.loader import SkillError
from cortex_leads.skills.manifest import parse_duration
from cortex_leads.skills.registry import TURN_EVENT, promote, retire

router = APIRouter()
TOOL_LABELS = {"read_messages": "Đọc tin nhắn gần nhất (đã che tên, SĐT)", "read_contact": "Đọc hồ sơ khách", "lookup_catalog": "Tra catalog giá và lịch",
               "study_plan": "Tính lộ trình học", "list_open_slots": "Xem lịch học thử còn chỗ", "book_slot": "Giữ chỗ học thử",
               "draft_followup": "Soạn nháp cho nhân viên duyệt", "send_message": "Gửi tin cho khách"}
LOCKED = ["Tự gửi tin cho khách (chỉ soạn nháp)", "Đặt lịch, gửi phiếu đăng ký", "Dùng nguồn dữ liệu ngoài", "Sửa luật chung hay bỏ cụm cấm đã có"]
ALWAYS = "Mọi số, ngày, giờ, đường dẫn trong nháp phải khớp catalog; bị chặn thì AI viết lại một lần rồi chuyển người."


def trigger_text(manifest: dict[str, Any], intents: dict[str, Any] | None = None) -> str:
    t = manifest.get("trigger") or {}
    on, after, match = t.get("on"), t.get("after"), t.get("match") or {}
    if on == TURN_EVENT:
        return "Khách nhắn xong, chưa ai trả lời"
    if on == "conversation.promised_date_reached":
        return "Tới ngày khách đã hẹn"
    if on == "lesson.recorded":
        return "Có bản ghi buổi học mới"
    if on == "submission.turned_in":
        return "Học sinh nộp bài trên Classroom"
    if on == "assignment.requested":
        return "Giáo viên nhờ soạn bài tập"
    hours = vi_duration(parse_duration(after)) if after else "24 giờ"
    who = ""
    if match.get("intent"):
        label = (intents or {}).get(match["intent"])
        who = f" ({label.label if label else match['intent']})"
    return f"Khách im {hours}{who}"


def _source(r: m.SkillVersion) -> str:
    return "custom" if r.name.startswith(PREFIX) else "card" if r.status == "shadow" else "system"


async def _counts(s: AsyncSession, r: m.SkillVersion) -> tuple[int, int]:
    base = (m.TriggerRun.sandbox_id == r.sandbox_id, m.TriggerRun.skill_name == r.name, m.TriggerRun.skill_version == r.version,
            *((m.TriggerRun.started_at >= r.edited_at,) if r.edited_at else ()))
    runs = (await s.execute(select(func.count()).select_from(m.TriggerRun).where(*base))).scalar_one()
    blocked = (await s.execute(select(func.count()).select_from(m.TriggerRun).where(
        *base, func.cardinality(m.TriggerRun.blocked_codes) > 0))).scalar_one()
    return runs, blocked


def _can(r: m.SkillVersion, ready: bool) -> dict[str, bool]:
    custom = r.name.startswith(PREFIX)
    gone = r.deleted_at is not None
    return {"trial": r.status == "draft" and custom and not gone, "live": r.status == "shadow" and ready and not gone,
            "off": r.status in ("live", "shadow") and (custom or r.status == "shadow") and not gone,
            "again": r.status == "retired" and custom and not gone,
            "edit": custom and r.form_spec is not None and not gone, "delete": custom and not gone, "restore": custom and gone}


async def _care(s: AsyncSession) -> m.Sandbox | None:
    return (await s.execute(select(m.Sandbox).where(m.Sandbox.purpose == "customer_care")
                            .order_by(m.Sandbox.created_at).limit(1))).scalar_one_or_none()


@router.get("/skills")
async def list_skills(sess: Session = need(Perm.SKILLS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sandboxes = {x.id: x for x in (await s.execute(select(m.Sandbox))).scalars()}
        every = (await s.execute(select(m.SkillVersion).order_by(m.SkillVersion.name, m.SkillVersion.version.desc()))).scalars().all()
        rows = [r for r in every if r.deleted_at is None]
        trash = [r for r in every if r.deleted_at is not None]
        groups: dict[tuple[UUID, str], list[m.SkillVersion]] = {}
        for r in rows:
            groups.setdefault((r.sandbox_id, r.name), []).append(r)
        shown = [r for g in groups.values() for r in ([x for x in g if x.status in ("live", "shadow")] or [g[0]])]
        items = []
        for r in [*sorted(shown, key=lambda x: (x.status != "live", x.name, -x.version)), *trash]:
            runs, blocked = await _counts(s, r)
            sb = sandboxes[r.sandbox_id]
            ready = runs >= MIN_SHADOW_RUNS
            items.append({"id": str(r.id), "name": r.name, "version": r.version, "description": r.manifest.get("description", ""),
                          "trigger": trigger_text(r.manifest, load_pack(sb).intents), "status": r.status, "source": _source(r),
                          "sandbox": label_of(sb), "runs": runs, "blocked": blocked, "ready": ready, "can": _can(r, ready),
                          "deleted": r.deleted_at is not None})
    kept = [i for i in items if not i["deleted"]]
    counts = {"all": len(kept), **{k: sum(1 for i in kept if i["status"] == k) for k in ("live", "shadow", "draft", "retired")},
              "deleted": len(items) - len(kept)}
    return {"items": items, "counts": counts, "min_trial_runs": MIN_SHADOW_RUNS}


@router.get("/skills/form-options")
async def form_options(sess: Session = need(Perm.SKILLS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await _care(s)
        intents = [{"id": k, "label": v.label} for k, v in (load_pack(sb).intents.items() if sb else [])]
    return {"templates": [{"id": k, "label": v} for k, v in TEMPLATES.items()], "intents": intents, "has_sandbox": sb is not None,
            "locked": LOCKED, "always": ALWAYS}


@router.get("/skills/{skill_id}")
async def skill_detail(skill_id: UUID, sess: Session = need(Perm.SKILLS_READ)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        r = await s.get(m.SkillVersion, skill_id)
        if r is None:
            raise HTTPException(404, "skill not found")
        sb = await s.get(m.Sandbox, r.sandbox_id)
        runs, blocked = await _counts(s, r)
        found = (await s.execute(
            select(m.Draft, m.TriggerRun).join(m.TriggerRun, m.TriggerRun.id == m.Draft.run_id)
            .where(m.TriggerRun.skill_name == r.name, m.TriggerRun.skill_version == r.version, m.Draft.status.in_(("shadow", "blocked")))
            .order_by(m.Draft.created_at.desc()).limit(10))).all()
        trial = []
        for d, _ in found:
            asked = (await s.execute(select(m.Message.text).where(m.Message.conversation_id == d.conversation_id,
                     m.Message.sender_role == "customer").order_by(m.Message.occurred_at.desc()).limit(1))).scalar_one_or_none()
            trial.append({"asked": (asked or "")[:200], "text": d.text, "blocked": d.status == "blocked"})
        await audit(sess, s, "view", "skill.viewed", f"Xem kỹ năng «{r.name}»", obj=("skill", str(r.id), r.name),
                    once_within=VIEW_ONCE)
    man = r.manifest
    ready = runs >= MIN_SHADOW_RUNS
    history = []
    if sess.can(Perm.SKILLS_MANAGE):
        async with tenant_session(sess.caller.tenant_id) as s:
            ev = (await s.execute(select(m.AuditEvent).where(m.AuditEvent.object_type == "skill", m.AuditEvent.object_id == str(r.id),
                                                             m.AuditEvent.category == "config").order_by(m.AuditEvent.seq.desc()).limit(15))).scalars().all()
        history = [{"id": str(e.id), "at": wire(e.at), "actor": e.actor, "summary": e.summary, "changes": (e.metadata_ or {}).get("changes", []),
                    "restorable": "before_spec" in (e.metadata_ or {}) and r.deleted_at is None} for e in ev]
    return {"id": str(r.id), "deleted": r.deleted_at is not None, "deleted_by": r.deleted_by,
            "deleted_at": wire(r.deleted_at) if r.deleted_at else None, "form": r.form_spec, "history": history,
            "body": r.body if sess.can(Perm.SKILLS_MANAGE) else None, "sandbox": label_of(sb), "created_at": wire(r.created_at), "name": r.name, "version": r.version, "description": man.get("description", ""), "status": r.status,
            "source": _source(r), "trigger": trigger_text(man, load_pack(sb).intents), "runs": runs, "blocked": blocked, "ready": ready,
            "min_trial_runs": MIN_SHADOW_RUNS, "can": _can(r, ready), "trial_drafts": trial,
            "tools": [TOOL_LABELS.get(t, t) for t in man.get("requires_tools", [])], "must_handoff": man.get("must_handoff", []),
            "never_say_count": len(man.get("never_say", [])), "limits": man.get("limits", {}),
            "sends": man.get("output_kind") == "send_to_customer"}


def _summary(spec: FormSpec, sandbox: m.Sandbox) -> dict[str, Any]:
    manifest, _ = build(spec, 1, sandbox)
    dump = manifest.model_dump(mode="json")
    return {"trigger": trigger_text(dump, load_pack(sandbox).intents), "tools": [TOOL_LABELS.get(t, t) for t in dump["requires_tools"]],
            "locked": LOCKED, "always": ALWAYS, "never_say_count": len(dump["never_say"]), "must_handoff": dump["must_handoff"]}


@router.post("/skills/preview")
async def preview_skill(spec: FormSpec, sess: Session = need(Perm.SKILLS_DRAFT)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await _care(s)
        if sb is None:
            raise HTTPException(409, {"code": "NO_SANDBOX"})
        return {"errors": await preview(s, sb.id, spec), "summary": _summary(spec, sb)}


@router.post("/skills", status_code=201)
async def create_skill(spec: FormSpec, sess: Session = need(Perm.SKILLS_DRAFT)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await _care(s)
        if sb is None:
            raise HTTPException(409, {"code": "NO_SANDBOX"})
        if errs := await preview(s, sb.id, spec):
            raise HTTPException(422, {"errors": errs})
        row = await save_draft(s, sess.caller.tenant_id, sb.id, spec)
        await audit(sess, s, "config", "skill.created", f"Tạo kỹ năng «{row.name}»", obj=("skill", str(row.id), row.name),
                    metadata={"version": row.version, "spec": spec.model_dump(mode="json")})
        return {"id": str(row.id), "name": row.name, "version": row.version}


VERB_TEXT = {"trial": "chạy thử", "live": "bật chạy thật", "off": "tắt", "again": "bật lại", "delete": "xoá (ẩn, khôi phục được)",
             "restore": "khôi phục"}


async def _edit(skill_id: UUID, spec: FormSpec | None, sess: Session, revert_event: UUID | None = None) -> dict[str, Any]:
    """Edit in place: same row, same version. A skill that is on (live or on trial) changes what the AI does at once, so only
    the owner may edit one; a draft is anyone's. The audit line keeps the form as it was, so a mistake can be put back."""
    async with tenant_session(sess.caller.tenant_id) as s:
        r = await s.get(m.SkillVersion, skill_id)
        if revert_event is not None:  # "put it back as it was before that change"
            ev = await s.get(m.AuditEvent, revert_event)
            if r is None or ev is None or ev.object_id != str(skill_id) or "before_spec" not in (ev.metadata_ or {}):
                raise HTTPException(404, "nothing to restore")
            spec = FormSpec(**ev.metadata_["before_spec"])
        if r is None or r.deleted_at is not None or not r.name.startswith(PREFIX):
            raise HTTPException(404, "skill not found")
        if r.form_spec is None:
            raise HTTPException(409, {"code": "NO_FORM", "message": "Kỹ năng này không tạo từ form nên không sửa ở đây được."})
        if r.status != "draft" and not sess.can(Perm.SKILLS_MANAGE):
            raise HTTPException(403, "owner only")
        before = dict(r.form_spec)
        if errs := await preview(s, r.sandbox_id, spec):
            raise HTTPException(422, {"errors": errs})
        try:
            await update_in_place(s, r, spec)
        except SkillError as e:
            raise HTTPException(422, {"errors": [str(e)]}) from None
        after = r.form_spec or {}
        await audit(sess, s, "config", "skill.edited", f"{'Khôi phục' if revert_event else 'Sửa'} kỹ năng «{r.name}»", obj=("skill", str(r.id), r.name),
                    changes=diff(before, after), metadata={"version": r.version, "status": r.status, "before_spec": before,
                                                          **({"restored_from": str(revert_event)} if revert_event else {})})
        return {"id": str(r.id), "name": r.name, "version": r.version, "status": r.status}


@router.put("/skills/{skill_id}")
async def edit_skill(skill_id: UUID, spec: FormSpec, sess: Session = need(Perm.SKILLS_DRAFT)) -> dict[str, Any]:
    return await _edit(skill_id, spec, sess)


class Revert(BaseModel):
    event_id: UUID


@router.post("/skills/{skill_id}/revert")
async def revert_skill(skill_id: UUID, body: Revert, sess: Session = need(Perm.SKILLS_DRAFT)) -> dict[str, Any]:
    return await _edit(skill_id, None, sess, body.event_id)


@router.post("/skills/{skill_id}/{verb}")
async def skill_verb(skill_id: UUID, verb: Literal["trial", "live", "off", "again", "delete", "restore"], sess: Session = need(Perm.SKILLS_MANAGE)) -> dict[str, str]:
    """Owner only: switching what the AI does is the owner's call."""
    async with tenant_session(sess.caller.tenant_id) as s:
        r = await s.get(m.SkillVersion, skill_id)
        if r is None or not (r.name.startswith(PREFIX) or r.status == "shadow"):  # form skills, and any trial
            raise HTTPException(404, "skill not found")
        if (r.deleted_at is not None) != (verb == "restore"):
            raise HTTPException(409, {"code": "NOT_DELETED" if verb == "restore" else "DELETED"})
        if verb in ("delete", "restore") and not r.name.startswith(PREFIX):
            raise HTTPException(409, {"code": "SKILL_RULE", "message": "Chỉ kỹ năng tạo từ form mới xoá được."})
        try:
            if verb == "delete":  # hidden and off, never gone: the row, its trial runs and its history stay
                if r.status in ("live", "shadow"):
                    await retire(s, r.sandbox_id, r.name, r.version)
                r.deleted_at, r.deleted_by = datetime.now(UTC), sess.actor
            elif verb == "restore":  # comes back switched off: turning it on is a separate, visible choice
                r.deleted_at, r.deleted_by = None, None
            elif verb == "trial":
                await start_trial(s, r.sandbox_id, r.name, r.version)
            elif verb == "live":
                await go_live(s, r.sandbox_id, r.name, r.version)
            elif verb == "again":
                await promote(s, r.sandbox_id, r.name, r.version, "live")
            else:
                await retire(s, r.sandbox_id, r.name, r.version)
        except SkillError as e:
            raise HTTPException(409, {"code": "SKILL_RULE", "message": str(e)}) from None
        await audit(sess, s, "config", f"skill.{verb}", f"Kỹ năng «{r.name}»: {VERB_TEXT[verb]}", obj=("skill", str(r.id), r.name),
                    metadata={"version": r.version, "status_after": r.status})
        status = r.status
    return {"status": status}

