"""Công cụ (WP29): what the AI can do, per sandbox. Three lists meet here and only their intersection runs:
the profile's allowlist (the sandbox's ceiling, from a file), what the owner switched off for this sandbox (`tools_off`), and
what each skill declares it needs. Switching a tool off is the owner's, audited, and takes effect on the next run."""
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from cortex_leads.auth.perms import Perm
from cortex_leads.console.auth import Session, need
from cortex_leads.console.flow import feeds_and_pushes
from cortex_leads.console.sandboxes import PURPOSE_LINES, label_of
from cortex_leads.console.skills import trigger_text
from cortex_leads.console.trail import audit
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session
from cortex_leads.sandbox.kinds import kind_of
from cortex_leads.skills.forms import PREFIX
from cortex_leads.skills.forms import TOOLS as FORM_TOOLS
from cortex_leads.skills.profile import load_profile
from cortex_leads.tools.registry import default_registry

router = APIRouter()
LEVELS = {"read": "Đọc", "internal": "Ghi nội bộ", "customer": "Gửi khách", "external": "Dữ liệu ngoài"}
CATALOG: dict[str, tuple[str, str]] = {
    "read_messages": ("Đọc tin nhắn", "Đọc các tin gần nhất, đã che tên và SĐT"),
    "read_contact": ("Đọc hồ sơ khách", "Ý định, người quyết định, hẹn của khách"),
    "lookup_catalog": ("Tra catalog", "Giá, lịch, chính sách. Nguồn duy nhất của mọi con số"),
    "study_plan": ("Lộ trình học", "Tính giờ tự học theo điểm hiện tại và mục tiêu"),
    "list_open_slots": ("Xem lịch học thử", "Các buổi còn chỗ"),
    "book_slot": ("Giữ chỗ học thử", "Giữ một chỗ sau khi khách chọn rõ"),
    "draft_followup": ("Soạn nháp", "Soạn tin cho nhân viên duyệt, qua bộ kiểm số liệu"),
    "send_message": ("Gửi tin cho khách", "Đường duy nhất tới khách: nháp, hộp gửi, kênh"),
    "external_lookup": ("Nguồn dữ liệu ngoài", "Đọc nguồn HTTP hoặc MCP đã ghim"),
    "record_facts": ("Ghi điều khách đã nói", "Lưu điều khách nói rõ vào trí nhớ, kèm bằng chứng"),
    "list_dropped_leads": ("Khách bị bỏ sót", "Hội thoại khách nhắn mà chưa ai trả lời"),
}
CONSEQUENCE = {
    "book_slot": "khách chọn lịch sẽ được chuyển cho nhân viên xếp tay.",
    "send_message": "nháp vẫn soạn nhưng nhân viên phải tự gửi.",
    "lookup_catalog": "AI không có số liệu để báo, các nháp có giá hay lịch sẽ bị chặn.",
    "draft_followup": "AI không soạn được nháp nào.",
}
SAFETY = {
    "book_slot": ["Chỉ hệ thống gọi, AI chỉ được xem danh sách lịch còn chỗ", "Chỗ được khoá, không vượt sức chứa", "Tin xác nhận bị chặn thì chỗ được nhả lại"],
    "send_message": ["Chỉ có một đường tới khách: nháp, hộp gửi, kênh", "Bị chặn ở kỹ năng, ở kênh và khi sandbox đang dừng"],
    "external_lookup": ["Dữ liệu ngoài không đáng tin: chỉ gắn cho sandbox không nói chuyện với khách", "Sau khi đọc, lượt đó không được ghi gì"],
}


def level_of(name: str) -> str:
    spec = default_registry()._tools.get(name)
    if spec is None:
        return "read"
    return "external" if spec.taints else spec.effect


def tool_row(name: str) -> dict[str, Any]:
    label, about = CATALOG.get(name, (name, ""))
    return {"name": name, "label": label, "about": about, "level": level_of(name), "level_label": LEVELS[level_of(name)]}


async def _skills(s: Any, sandbox_id: UUID) -> list[m.SkillVersion]:
    rows = (await s.execute(select(m.SkillVersion).where(m.SkillVersion.sandbox_id == sandbox_id, m.SkillVersion.deleted_at.is_(None),
                                                       m.SkillVersion.status.in_(("live", "shadow"))).order_by(m.SkillVersion.name))).scalars().all()
    return list(rows)


@router.get("/tools")
async def list_tools(sess: Session = need(Perm.TOOLS_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sandboxes = (await s.execute(select(m.Sandbox).order_by(m.Sandbox.created_at))).scalars().all()
        sources = (await s.execute(select(func.count()).select_from(m.ToolConnector).where(m.ToolConnector.deleted_at.is_(None)))).scalar_one()
        channels = (await s.execute(select(func.count()).select_from(m.Connector))).scalar_one()
        skills = [(sb, r) for sb in sandboxes for r in await _skills(s, sb.id)]
    names: list[str] = []
    allow: dict[UUID, set[str]] = {}
    for sb in sandboxes:
        got = {t for t in load_profile(sb.profile_ref).tool_allowlist if t not in (sb.tools_off or [])}
        allow[sb.id] = got
        names += [t for t in load_profile(sb.profile_ref).tool_allowlist if t not in names]
    items = []
    for n in names:
        items.append({**tool_row(n), "sandboxes": [{"id": str(sb.id), "title": label_of(sb), "on": n in allow[sb.id]} for sb in sandboxes
                                                  if n in load_profile(sb.profile_ref).tool_allowlist],
                      "skills": sum(1 for sb, r in skills if n in allow[sb.id] and n in r.manifest.get("requires_tools", []))})
    return {"items": items, "levels": LEVELS, "counts": {"tools": len(items), "sources": sources, "channels": channels}}


def _cell(name: str, on: bool, needs: bool, form: bool) -> str:
    if form and name not in FORM_TOOLS:
        return "locked"  # a form skill can never use it, whatever the sandbox allows
    if not on:
        return "blocked" if needs else "off"
    return "uses" if needs else "allowed"


def _send_view(sb: m.Sandbox, skills: list[m.SkillVersion], conns: list[m.Connector]) -> dict[str, Any]:
    """Why a message does or does not leave without a person: what the sandbox says, what each skill allows, what each channel permits."""
    from cortex_leads.skills.manifest import SkillManifest
    from cortex_leads.tools.send import effective_mode

    rows = []
    for r in skills:
        man = SkillManifest(**r.manifest)
        eff = effective_mode(man, sb)
        capable = man.output_kind == "send_to_customer" and "send_message" in man.requires_tools
        why = ("Soạn nháp: kỹ năng này luôn chờ nhân viên duyệt." if not capable else
               "Tự gửi khi đủ điều kiện." if eff == "auto" else "Đang ở chế độ duyệt tay của sandbox.")
        rows.append({"name": r.name, "can_auto": capable, "effective": eff, "why": why})
    channels = []
    for c in conns:
        out = c.outbound or {}
        problems = [t for ok, t in ((bool(out.get("enabled") and out.get("url")), "Kênh chưa bật gửi từ hệ thống"),
                                    (c.trust in ("official", "partner") and not (c.trust == "partner" and c.contract_test_passed_at is None),
                                     "Kênh chưa được tin cậy để gửi"), (c.status == "active", "Kênh đang tắt")) if not ok]
        channels.append({"kind": c.channel_kind, "can_send": not problems, "problems": problems})
    return {"mode": sb.send_mode, "skills": rows, "channels": channels,
            "auto_possible": any(r["can_auto"] for r in rows) and any(c["can_send"] for c in channels)}


@router.get("/sandboxes/{sandbox_id}")
async def sandbox_detail(sandbox_id: UUID, sess: Session = need(Perm.TOOLS_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await s.get(m.Sandbox, sandbox_id)
        if sb is None:
            raise HTTPException(404, "sandbox not found")
        profile = load_profile(sb.profile_ref)
        skills = await _skills(s, sb.id)
        conns = (await s.execute(select(m.Connector).where(m.Connector.sandbox_id == sb.id))).scalars().all()
        sources = (await s.execute(select(m.ToolConnector).where(m.ToolConnector.sandbox_id == sb.id, m.ToolConnector.deleted_at.is_(None)))).scalars().all()
        catalog = (await s.execute(select(func.count()).select_from(m.CatalogItem).where(m.CatalogItem.active.is_(True)))).scalar_one()
        feeds, pushes = await feeds_and_pushes(s, sb)
    kind = kind_of(sb.purpose)
    off = set(sb.tools_off or [])
    tools = [{**tool_row(n), "on": n not in off, "skills": [r.name for r in skills if n in r.manifest.get("requires_tools", [])]} for n in profile.tool_allowlist]
    rows = []
    for r in skills:
        needs = set(r.manifest.get("requires_tools", []))
        form = r.name.startswith(PREFIX)
        cells = {t["name"]: _cell(t["name"], t["on"], t["name"] in needs, form) for t in tools}
        rows.append({"id": str(r.id), "name": r.name, "status": r.status, "source": "custom" if form else "system", "trigger": trigger_text(r.manifest),
                     "cells": cells, "uses": sum(1 for v in cells.values() if v == "uses"), "total": len(tools)})
    send = _send_view(sb, skills, conns)
    return {"id": str(sb.id), "title": label_of(sb), "purpose": sb.purpose, "send": send, "about": PURPOSE_LINES.get(sb.purpose, ""), "status": sb.status,
            "profile": {"id": profile.id, "version": profile.version, "ceiling": LEVELS.get(profile.effect_ceiling, profile.effect_ceiling), "max_tool_calls": profile.max_tool_calls},
            "inputs": {"channels": [{"kind": c.channel_kind, "status": c.status, "sends": bool((c.outbound or {}).get("enabled"))} for c in conns],
                       "catalog_items": catalog,
                       "sources": [{"id": str(x.id), "name": x.name, "kind": x.kind, "status": x.status} for x in sources]},
            "facing": {"customer": bool(kind and kind.customer_facing), "tools": bool(profile.tool_allowlist)},
            "feeds": feeds, "pushes": pushes,
            "tools": tools, "skills": rows, "levels": LEVELS}


@router.get("/sandboxes/{sandbox_id}/tools/{tool}")
async def tool_in_sandbox(sandbox_id: UUID, tool: str, sess: Session = need(Perm.TOOLS_MANAGE)) -> dict[str, Any]:
    d = await sandbox_detail(sandbox_id, sess)
    t = next((x for x in d["tools"] if x["name"] == tool), None)
    if t is None:
        raise HTTPException(404, "tool not found")
    names = ", ".join(t["skills"])
    return {**t, "sandbox": d["title"], "safety": SAFETY.get(tool, []),
            "if_off": f"{names}: {CONSEQUENCE.get(tool, 'kỹ năng dùng nó sẽ không chạy được.')}" if t["skills"] else None}


@router.post("/sandboxes/{sandbox_id}/tools/{tool}/{state}")
async def switch_tool(sandbox_id: UUID, tool: str, state: Literal["on", "off"], sess: Session = need(Perm.TOOLS_MANAGE)) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        sb = await s.get(m.Sandbox, sandbox_id)
        if sb is None:
            raise HTTPException(404, "sandbox not found")
        if tool not in load_profile(sb.profile_ref).tool_allowlist:
            raise HTTPException(409, {"code": "TOOL_NOT_IN_PROFILE", "message": "Hồ sơ AI của sandbox này không có công cụ đó, không thể bật thêm."})
        before = list(sb.tools_off or [])
        after = sorted({*before, tool} if state == "off" else set(before) - {tool})
        if after != before:
            sb.tools_off = after
            await audit(sess, s, "config", f"tool.{state}", f"{'Tắt' if state == 'off' else 'Bật'} công cụ «{CATALOG.get(tool, (tool,))[0]}» cho sandbox «{label_of(sb)}»",
                        obj=("sandbox", str(sb.id), label_of(sb)), metadata={"tool": tool, "tools_off_before": before, "tools_off_after": after})
    return {"tool": tool, "on": state == "on"}
