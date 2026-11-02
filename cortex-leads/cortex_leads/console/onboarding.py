"""The first run (WP43): four steps from an empty business to a first draft, each read from what actually exists, so the page never
says "done" about something that is not."""
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from cortex_leads.console.auth import Session, need
from cortex_leads.db import models as m
from cortex_leads.db.session import tenant_session

router = APIRouter()


@router.get("/onboarding")
async def onboarding(sess: Session = need("settings.manage")) -> dict[str, Any]:
    tid = sess.caller.tenant_id
    async with tenant_session(tid) as s:
        channels = (await s.execute(select(func.count()).select_from(m.Connector).where(m.Connector.tenant_id == tid, m.Connector.status == "active"))).scalar_one()
        catalog = (await s.execute(select(func.count()).select_from(m.CatalogItem))).scalar_one()
        skills = (await s.execute(select(func.count()).select_from(m.SkillVersion).join(m.Sandbox, m.Sandbox.id == m.SkillVersion.sandbox_id).where(
            m.Sandbox.purpose == "customer_care", m.SkillVersion.status.in_(("live", "shadow")), m.SkillVersion.deleted_at.is_(None)))).scalar_one()
        talked = (await s.execute(select(func.count()).select_from(m.Conversation))).scalar_one()
        drafts = (await s.execute(select(func.count()).select_from(m.Draft))).scalar_one()
    steps = [
        {"id": "channel", "title": "Nối kênh nhắn tin", "done": channels > 0, "count": channels, "href": "/settings?tab=channels",
         "hint": "Tạo kênh, rồi dán mã vào bridge (Pancake/Messenger) để tin của khách chảy vào."},
        {"id": "catalog", "title": "Nhập bảng giá và lịch học", "done": catalog > 0, "count": catalog, "href": None,
         "hint": "Mọi con số AI nói với khách phải có trong bảng này. Nhập bằng lệnh `cli import-catalog` hoặc màn catalog (sẽ có sau)."},
        {"id": "skills", "title": "Bật kỹ năng trả lời", "done": skills > 0, "count": skills, "href": "/skills",
         "hint": "Chạy thử (shadow) rồi bật chạy thật. Ở chế độ duyệt tay, AI chỉ soạn nháp."},
        {"id": "first_draft", "title": "Có hội thoại và nháp đầu tiên", "done": talked > 0 and drafts > 0, "count": drafts, "href": "/inbox",
         "hint": "Nhắn thử một tin từ kênh vừa nối; nháp sẽ hiện ở Hộp thư để nhân viên xem và gửi."},
    ]
    return {"steps": steps, "complete": all(x["done"] for x in steps), "done": sum(x["done"] for x in steps)}
