"""Kịch bản chuẩn (DESIGN §5.12) ở chế độ giả lập: không mạng, FakeProvider, Postgres thật.

    python -m dev.scenario        # cần CL_* trong env và DB đã `make migrate`

Mỗi bước in một dòng tiếng Việt. Thời gian được "tua": sự kiện đặt lùi 30 giờ rồi quét đồng hồ ở `now`.
Tin đi qua đường duy nhất send_message -> outbox -> worker -> bridge Messenger (ASGI, Graph API giả).
Chiều vào vẫn dựng event bằng tay đúng quy tắc của bridge (echo không app_id = staff)."""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet
from sqlalchemy import select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from bridges.gsheet.sheet import orders_to_events
from bridges.messenger.app import Settings as MessengerSettings
from bridges.messenger.app import create_app as messenger_app
from bridges.pancake.run import post_events
from bridges.twenty import app as twenty_app
from cortex_leads.app import create_app
from cortex_leads.clock.sweeper import sweep_once
from cortex_leads.config import get_settings
from cortex_leads.core.ids import new_connector_id, uuid7
from cortex_leads.db import models as m
from cortex_leads.db.session import get_engine, system_session, tenant_session
from cortex_leads.domain.pack import load_pack_file
from cortex_leads.guard.facts import extract_date_candidates
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.providers import FakeProvider
from cortex_leads.llm.types import LLMResult, ToolCall
from cortex_leads.outbound.worker import deliver_once
from cortex_leads.runner.customer_run import run_pending
from cortex_leads.skills.loader import sync_dir
from cortex_leads.skills.registry import promote

ROOT = Path(__file__).resolve().parents[1]
CARE = ROOT / "sandboxes" / "customer_care"
PAGE, PSID = "page_sim", "psid_1001"
PSID_FREE, PSID_LATE = "psid_2002", "psid_3003"  # step 10: free window / past the free window
MORE = "Em đang hỏi lại chồng, có gì em nhắn shop sau"
ASK = "Chào shop, em là An, sđt 0901 234 567. Khóa IELTS giá bao nhiêu?"
STAFF = "Dạ khóa IELTS bên em có nhiều lớp, chị xem giúp em nhé"
PROMISE = "Tuần sau chị bàn với chồng rồi báo shop nhé"
DRAFT = {"act": "draft", "reason_code": "khong_ro", "has_new_info": True,
         "claims": [{"value": 2_500_000, "source_id": "KH01"}],
         "text": "Chào chị, khóa IELTS bên em giá 2.500.000đ, chị cần em tư vấn thêm không ạ?"}


def messenger_event(mid: str, text: str, at: datetime, *, staff: bool = False, psid: str = PSID) -> dict[str, Any]:
    """Event Format v1 như bridge Messenger sẽ sinh (WP10 chốt quy tắc vai trò)."""
    return {"type": "message.created", "external_id": f"messenger:{PAGE}:{mid}", "occurred_at": at.isoformat(),
            "channel": {"kind": "messenger", "account_ref": PAGE}, "conversation": {"external_id": psid},
            "contact": {"external_id": psid, "display_name": "Nguyễn Văn An"},
            "sender": {"role": "staff" if staff else "customer"}, "text": text}


def fake_llm() -> LLMGateway:
    call = LLMResult(content=None, tool_calls=[ToolCall("c1", "lookup_catalog", {"query": "KH01"})],
                     tokens_in=50, tokens_out=5, model="fake")
    final = LLMResult(content=json.dumps(DRAFT, ensure_ascii=False), tokens_in=100, tokens_out=20, model="fake")
    return LLMGateway(FakeProvider([call, final]), retry_delay_s=0)


def facts_llm(promise_on: str) -> LLMGateway:
    """The model reads the promise and the decision maker out of the customer's own words (N5)."""
    out = {"act": "none", "facts": [
        {"kind": "promised_date", "value": {"date": promise_on}, "evidence": ["m3"]},
        {"kind": "decision_maker", "value": {"role": "vo_chong"}, "evidence": ["m3"]}]}
    return LLMGateway(FakeProvider([LLMResult(content=json.dumps(out), tokens_in=80, tokens_out=30, model="fake")]),
                      retry_delay_s=0)


def fake_llm_n(n: int) -> LLMGateway:
    """n runs of: look up the catalog, then write the same draft."""
    call = LLMResult(content=None, tool_calls=[ToolCall("c1", "lookup_catalog", {"query": "KH01"})],
                     tokens_in=50, tokens_out=5, model="fake")
    final = LLMResult(content=json.dumps(DRAFT, ensure_ascii=False), tokens_in=100, tokens_out=20, model="fake")
    return LLMGateway(FakeProvider([call, final] * n), retry_delay_s=0)


async def seed() -> dict[str, Any]:
    tid, sid, cid, secret = uuid7(), uuid7(), new_connector_id(), secrets.token_urlsafe(24)
    staff_key = f"clk_{secrets.token_urlsafe(24)}"
    sup_key = f"clk_{secrets.token_urlsafe(24)}"
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name=f"sim-{tid.hex[:6]}"))
    async with tenant_session(tid) as s:
        s.add(m.Sandbox(id=sid, tenant_id=tid, name="customer_care", profile_ref="customer_drafter@1",
                        domain_pack=load_pack_file(CARE / "domain.yaml").model_dump(mode="json"),
                        budget={"runs_per_day": 100, "drafts_per_staff_per_day": 20, "tokens_per_day": 100000},
                        business_hours={"start": "00:00", "end": "23:59"}))  # the sim must not wait for 8h
        s.add(m.CatalogItem(tenant_id=tid, code="KH01", name="Khóa IELTS", price=2_500_000))
    async with system_session() as s:
        s.add(m.Connector(id=cid, tenant_id=tid, sandbox_id=sid, channel_kind="messenger", trust="official",
                          outbound={"enabled": True, "url": "http://messenger-bridge/actions"},
                          secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(secret.encode())))
        for role, ref, key in (("staff", "nv1", staff_key), ("supervisor", None, sup_key)):
            s.add(m.ApiKey(tenant_id=tid, role=role, staff_ref=ref, key_hash=hashlib.sha256(key.encode()).hexdigest()))
    async with tenant_session(tid) as s:
        await sync_dir(s, tid, sid, CARE / "skills")
        for status in ("shadow", "live"):
            await promote(s, sid, "hoi-lai-khach-im", 3, status)
    return {"tenant": tid, "connector": cid, "secret": secret, "staff": {"X-Api-Key": staff_key},
            "sup": {"X-Api-Key": sup_key}}


async def conv_state(tid) -> str:
    async with tenant_session(tid) as s:
        return (await s.execute(select(m.Conversation.state))).scalars().first()


async def run_scenario(say: Callable[[str], None] = print, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    t0, out = now - timedelta(hours=30), {}
    w = await seed()
    tid = w["tenant"]
    core = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://core")
    ingest = "http://core/ingest/v1/events"
    graph: list[dict[str, Any]] = []  # what the Graph API would have received

    def graph_api(req: httpx.Request) -> httpx.Response:
        graph.append(json.loads(req.content))
        return httpx.Response(200, json={"message_id": f"mid.sim{len(graph)}"})

    bridge = messenger_app(
        MessengerSettings(app_secret="sim", verify_token="sim", page_token="sim-page-token", page_id=PAGE,
                          own_app_id="sim-app", ingest_url=ingest, connector_id=w["connector"],
                          connector_secret=w["secret"], policy={"ai_send": True}),
        http=httpx.AsyncClient(transport=httpx.MockTransport(graph_api)), data_dir=Path(tempfile.mkdtemp()))
    to_bridge = httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge), base_url="http://messenger-bridge")

    async def send(events: list[dict]) -> list[str]:
        r = await post_events(core, ingest, w["connector"], w["secret"], events)
        return [k for k, v in r.items() if v for _ in range(v)]

    say(f"[0] Dựng tenant sim {str(tid)[:8]}, connector {w['connector']}, skill hoi-lai-khach-im đã live.")
    say(f"[1] Tester hỏi giá lúc {t0:%H:%M %d/%m} -> {await send([messenger_event('m1', ASK, t0)])}")
    r = await send([messenger_event("m2", STAFF, t0 + timedelta(hours=1), staff=True)])
    say(f"[2] Nhân viên trả lời trong hộp thư Page (echo không app_id = staff) -> {r}")
    say(f"[3] Tua tới {now:%H:%M %d/%m}: khách im 29 giờ; đồng hồ bắn {await sweep_once(now)} hội thoại.")
    runs = await run_pending(now, fake_llm())
    r = await core.get("/review/drafts", headers=w["staff"])
    drafts = r.json()["drafts"]
    out["drafts"] = drafts
    say(f"[4] FakeProvider soạn {runs} nháp: {drafts[0]['text']!r} (cửa sổ {drafts[0]['window']['basis']})")
    r = await core.post(f"/review/drafts/{drafts[0]['id']}/action", json={"action": "approved"}, headers=w["staff"])
    out["approve_status"] = r.status_code
    delivered = await deliver_once(datetime.now(UTC), client=to_bridge)  # the review API ran on the wall clock
    out["graph"] = list(graph)
    async with tenant_session(tid) as s:
        out["staff_outbox"] = (await s.execute(select(m.Outbox.status).where(m.Outbox.actor.like("staff:%")))).scalars().all()
    tag = graph[0].get("tag") if graph else None
    say(f"[5] Nhân viên bấm 'Duyệt & gửi' -> HTTP {r.status_code}; worker xử lý {delivered} tin -> {out['staff_outbox']} "
        f"(Graph API giả nhận {len(graph)}, tag {tag}: cửa sổ HUMAN_AGENT chỉ người duyệt mới gửi được).")

    # --- trí nhớ: lời hẹn + người quyết định, rồi đợt im kế tiếp không tốn token ---
    r = await send([messenger_event("m3", PROMISE, now + timedelta(minutes=5))])
    t_run = now + timedelta(hours=26)
    tz = "Asia/Ho_Chi_Minh"
    promise_on = min(extract_date_candidates(PROMISE, t_run, tz)).isoformat()
    await sweep_once(t_run)
    await run_pending(t_run, facts_llm(promise_on))
    async with tenant_session(tid) as s:
        conv = (await s.execute(select(m.Conversation).where(m.Conversation.external_id == PSID))).scalar_one()
        contact = await s.get(m.Contact, conv.contact_id)
        out["promised_date"], out["decision_maker"] = conv.promised_date, contact.decision_maker
    say(f"[6] Tester: {PROMISE!r} -> {r}. Model đọc lời khách -> promised_date={out['promised_date']}, "
        f"decision_maker={out['decision_maker']}.")
    await send([messenger_event("m4", MORE, t_run + timedelta(minutes=10))])
    async with tenant_session(tid) as s:  # tua đồng hồ: lại im, nhưng khách đã hẹn ngày
        await s.execute(update(m.Conversation).where(m.Conversation.external_id == PSID).values(
            next_check_at=t_run + timedelta(hours=1)))
    quiet = FakeProvider([])  # any LLM call would raise
    await sweep_once(t_run + timedelta(days=1))
    await run_pending(t_run + timedelta(days=1), LLMGateway(quiet, retry_delay_s=0))
    out["llm_calls_after_promise"] = len(quiet.calls)
    say(f"[6b] Đợt im kế tiếp (khách còn đang trong lời hẹn): số lần gọi LLM = {len(quiet.calls)}.")

    # --- Twenty: deal Won (qua cầu nối Twenty thật, chữ ký Twenty thật) ---
    env = {"TWENTY_WEBHOOK_SECRET": "twenty-sim", "CL_INGEST_URL": ingest, "CL_CONNECTOR_ID": w["connector"],
           "CL_CONNECTOR_SECRET": w["secret"], "TWENTY_STAGE_MAP": json.dumps({"WON": "won"})}
    bridge = httpx.AsyncClient(transport=httpx.ASGITransport(app=twenty_app.create_app(core, env=env)),
                               base_url="http://twenty-bridge")
    payload = {"event": "opportunity.updated", "timestamp": (now + timedelta(days=1)).isoformat(), "data": {
        "id": "opp-sim-1", "stage": "WON", "amount": {"amountMicros": 2_500_000_000_000, "currencyCode": "VND"},
        "pointOfContact": {"cortexRef": f"{w['connector']}:{PSID}"}}}
    body, ts = json.dumps(payload).encode(), str(int(time.time()))
    sig = hmac.new(b"twenty-sim", ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    r = await bridge.post("/webhook", content=body, headers={
        "X-Twenty-Webhook-Signature": sig, "X-Twenty-Webhook-Timestamp": ts})
    out["twenty"], out["state"] = r.json(), await conv_state(tid)
    ok = r.json().get("accepted") == 1
    say(f"[7] Twenty: deal Won (cortexRef -> khách) -> {r.json()}; trạng thái hội thoại: {out['state']}"
)

    # --- Google Sheet: đơn ghi tay, poll hai lần ---
    sheet = (ROOT / "dev" / "samples" / "orders.csv").read_text().splitlines()[0] + \
        f"\nDH-SIM,{w['connector']}:psid_unknown,won,900000,{now:%Y-%m-%d}\n"
    out["sheet"] = [await send(orders_to_events(sheet)), await send(orders_to_events(sheet))]
    say(f"[8] Sheet đơn hàng (khách không khớp -> không đoán): lần 1 {out['sheet'][0]}, lần 2 {out['sheet'][1]}")

    # --- Số liệu cho người giám sát: không có chữ của khách ---
    blob = (await core.get("/supervisor/summary", headers=w["sup"])).text
    leaked = [x for x in ("IELTS", "2.500.000", "0901", "Nguyễn", "chồng", drafts[0]["text"]) if x in blob]
    out["leaked"] = leaked
    say(f"[9] Số liệu tổng cho giám sát: {'KHÔNG lộ chữ của khách' if not leaked else f'LỘ: {leaked}'}.")

    # --- chạy lại ở chế độ auto: skill thử `thu-nhanh`, hai khách ---
    async with tenant_session(tid) as s:
        await s.execute(update(m.Sandbox).values(send_mode="auto"))
        sb_id = (await s.execute(select(m.Sandbox.id))).scalar_one()
        for status in ("shadow", "live"):
            await promote(s, sb_id, "thu-nhanh", 1, status)
    evs = [messenger_event("f1", ASK, now - timedelta(hours=3), psid=PSID_FREE),
           messenger_event("f2", STAFF, now - timedelta(hours=2), staff=True, psid=PSID_FREE),
           messenger_event("l1", ASK, now - timedelta(hours=30), psid=PSID_LATE),
           messenger_event("l2", STAFF, now - timedelta(hours=29), staff=True, psid=PSID_LATE)]
    await send(evs)
    async with tenant_session(tid) as s:  # tua 5 phút im của skill thử
        await s.execute(update(m.Conversation).where(m.Conversation.external_id == PSID_FREE).values(
            next_check_at=now - timedelta(minutes=1)))
    await sweep_once(now)
    await run_pending(now, fake_llm_n(2))
    before = len(graph)
    await deliver_once(datetime.now(UTC), client=to_bridge)
    async with tenant_session(tid) as s:
        outbox = list((await s.execute(select(m.Outbox))).scalars())
        falls = list((await s.execute(select(m.DecisionLog).where(m.DecisionLog.decision == "fallback_manual"))).scalars())
        proposed = (await s.execute(select(m.Conversation.external_id).join(
            m.Draft, m.Draft.conversation_id == m.Conversation.id).where(m.Draft.status == "proposed"))).scalars().all()
    ai_out = [o for o in outbox if o.actor.startswith("ai:")]
    out["auto"] = {"sent": [o.status for o in ai_out], "graph": len(graph) - before, "fallbacks": len(falls),
                   "manual_for": sorted(proposed)}
    say(f"[10] Chế độ auto: khách còn cửa sổ tự do -> {len(ai_out)} tin tự gửi ({[o.status for o in ai_out]}, "
        f"kèm dòng 'Trợ lý AI'); khách quá 24h (HUMAN_AGENT) -> rơi về manual ({PSID_LATE} có nháp chờ duyệt, "
        f"{len(falls)} dòng decision_log fallback_manual).")
    out["deal_supported"] = ok
    return out


async def main() -> int:
    """R41: run in a private database. On a shared one, another agent's `pytest` TRUNCATEs the tables
    mid-scenario (NoResultFound / FK errors), and sweep/run_pending also pick up leftover tenants."""
    owner = make_url(os.environ["CL_DATABASE_OWNER_URL"])
    name = f"cortex_leads_sim_{secrets.token_hex(4)}"
    admin = create_async_engine(owner, isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        await c.execute(text(f'CREATE DATABASE "{name}"'))
    env = {"CL_DATABASE_OWNER_URL": owner.set(database=name).render_as_string(hide_password=False),
           "CL_DATABASE_URL": make_url(os.environ["CL_DATABASE_URL"]).set(database=name)
           .render_as_string(hide_password=False)}
    try:
        os.environ.update(env)
        get_settings.cache_clear()
        subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True,
                       capture_output=True)
        return 1 if (await run_scenario())["leaked"] else 0
    finally:
        await get_engine().dispose()
        async with admin.connect() as c:
            await c.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await admin.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
