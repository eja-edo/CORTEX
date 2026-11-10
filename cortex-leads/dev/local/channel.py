"""Messenger giả (dev): vào = Event Format v1 ký HMAC tới /ingest; ra = nhận Action Format v1 tại
/actions (bridge giả). Chỉ là một bridge: tin đi ra khách vẫn CHỈ qua send_message -> outbox -> worker (A9)."""
import asyncio
import json
import logging
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from cortex_leads.channels.policy import window_state
from cortex_leads.ingest.signing import sign, verify
from dev.local import env
from dev.local.page import PAGE_HTML

log = logging.getLogger("dev.local.channel")
REWIND_CHOICES = {1, 6, 21, 25, 192}  # giờ; 192 = 8 ngày
# (bảng, cột thời gian, điều kiện theo conversation :c). promised_date xử lý riêng (kiểu date).
_REWIND = [
    ("message", ["occurred_at"], "conversation_id = :c"),
    ("conversation", ["last_customer_at", "last_staff_at", "next_check_at", "reply_check_at", "updated_at"], "id = :c"),
    ("followup_job", ["not_before", "created_at", "updated_at"], "conversation_id = :c"),
    ("draft", ["created_at", "decided_at"], "conversation_id = :c"),
    ("outbox", ["created_at", "sent_at", "not_before"], "conversation_id = :c"),
    ("staff_action", ["at"], "draft_id in (select id from draft where conversation_id = :c)"),
]


class ChatStore:
    """Lịch sử chat phía 'điện thoại' của khách, lưu ra data/local_chat.json."""

    def __init__(self) -> None:
        try:
            self.d = json.loads(env.CHAT_FILE.read_text())
        except (OSError, ValueError):
            self.d = {"customers": [], "messages": {}, "actions": {}}

    def save(self) -> None:
        env.DATA.mkdir(exist_ok=True)
        tmp = env.CHAT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.d, ensure_ascii=False))
        tmp.replace(env.CHAT_FILE)

    def name(self, psid: str) -> str | None:
        return next((c["name"] for c in self.d["customers"] if c["psid"] == psid), None)

    def add_customer(self, name: str, psid: str | None = None) -> dict[str, str]:
        c = {"psid": psid or f"psid_{secrets.token_hex(3)}", "name": name}
        self.d["customers"].append(c)
        self.save()
        return c

    def add_message(self, psid: str, who: str, body: str, **extra: Any) -> dict[str, Any]:
        msg = {"at": datetime.now(UTC).isoformat(), "who": who, "text": body, **extra}
        self.d["messages"].setdefault(psid, []).append(msg)
        self.save()
        return msg


def create_channel_app(local: dict[str, str], tick: Callable[[], Awaitable[dict[str, Any]]]) -> FastAPI:
    cid, secret = local["LOCAL_CONNECTOR_ID"], local["LOCAL_CONNECTOR_SECRET"].encode()
    tenant = local["LOCAL_TENANT_ID"]
    store = ChatStore()
    box: dict[str, Any] = {}

    async def ingest(events: list[dict[str, Any]]) -> None:
        body = json.dumps({"format": "cortex.event/1", "events": events}).encode()
        ts = int(time.time())
        r = await box["http"].post(f"{env.CORE_URL}/ingest/v1/events", content=body, headers={
            "X-Connector-Id": cid, "X-Timestamp": str(ts), "X-Signature": sign(secret, ts, body),
            "Content-Type": "application/json"})
        r.raise_for_status()
        bad = [x for x in r.json()["results"] if x["status"] == "rejected"]
        if bad:
            raise HTTPException(502, f"Lõi từ chối sự kiện: {bad[0].get('error')}")

    def event(mid: str, body: str, role: str, psid: str, *, name: str | None = None,
              meta: dict[str, Any] | None = None) -> dict[str, Any]:
        contact: dict[str, Any] = {"external_id": psid}
        if name:
            contact["display_name"] = name
        return {"type": "message.created", "external_id": f"messenger:{env.PAGE_ID}:{mid}",
                "occurred_at": datetime.now(UTC).isoformat(),
                "channel": {"kind": "messenger", "account_ref": env.PAGE_ID},
                "conversation": {"external_id": psid}, "contact": contact,
                "sender": {"role": role}, "text": body, "meta": meta or {}}

    async def tx(fn: Callable[[Any], Awaitable[Any]]) -> Any:
        async with box["engine"].begin() as conn:  # owner; vẫn đặt tenant phòng khi owner không bypass RLS
            await conn.execute(text("select set_config('app.tenant_id', :t, true)"), {"t": tenant})
            return await fn(conn)

    async def status(psid: str) -> dict[str, Any] | None:
        async def q(conn: Any) -> dict[str, Any] | None:
            row = (await conn.execute(text(
                "select id, state, touches, promised_date, intent, last_customer_at, next_check_at, "
                "offchannel_contact, channel_kind from conversation "
                "where connector_id = :k and external_id = :p"), {"k": cid, "p": psid})).mappings().first()
            if row is None:
                return None
            c = row["id"]
            drafts = (await conn.execute(text(
                "select status, route, count(*) n from draft where conversation_id = :c "
                "group by 1, 2"), {"c": c})).all()
            outbox = (await conn.execute(text(
                "select status, actor, reason from outbox where conversation_id = :c "
                "order by created_at desc limit 3"), {"c": c})).all()
            jobs = (await conn.execute(text(
                "select skill_name, status from followup_job where conversation_id = :c "
                "order by created_at desc limit 3"), {"c": c})).all()
            w = window_state(row["channel_kind"], row["last_customer_at"], datetime.now(UTC))
            return {"state": row["state"], "touches": row["touches"], "intent": row["intent"],
                    "promised_date": str(row["promised_date"]) if row["promised_date"] else None,
                    "offchannel_contact": row["offchannel_contact"],
                    "next_check_at": row["next_check_at"].isoformat() if row["next_check_at"] else None,
                    "last_customer_at": row["last_customer_at"].isoformat() if row["last_customer_at"] else None,
                    "window": w["basis"] if w["open"] else "closed",
                    "drafts": [f"{r[0]}/{r[1]} x{r[2]}" for r in drafts],
                    "outbox": [f"{r[0]} ({r[1]}{', ' + r[2] if r[2] else ''})" for r in outbox],
                    "jobs": [f"{r[0]}: {r[1]}" for r in jobs]}
        return await tx(q)

    async def rewind(psid: str, hours: int) -> dict[str, int]:
        async def q(conn: Any) -> dict[str, int]:
            c = (await conn.execute(text(
                "select id from conversation where connector_id = :k and external_id = :p"),
                {"k": cid, "p": psid})).scalar_one_or_none()
            if c is None:
                raise HTTPException(404, "Khách chưa có hội thoại trong lõi (hãy nhắn một tin trước).")
            touched = {}
            for table, cols, where in _REWIND:
                sets = ", ".join(f"{col} = {col} - make_interval(hours => :h)" for col in cols)
                res = await conn.execute(text(f"update {table} set {sets} where {where}"),
                                         {"c": c, "h": hours})
                touched[table] = res.rowcount
            await conn.execute(text(  # ngày hẹn là kiểu date: lùi theo số ngày tròn
                "update conversation set promised_date = (promised_date - make_interval(days => :d))::date "
                "where id = :c and promised_date is not null"), {"c": c, "d": hours // 24})
            return touched
        return await tx(q)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        box["http"] = httpx.AsyncClient(timeout=15)
        box["engine"] = create_async_engine(os.environ["CL_DATABASE_OWNER_URL"])
        yield
        await box["http"].aclose()
        await box["engine"].dispose()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def home() -> str:
        return PAGE_HTML.replace("__PAGE__", env.PAGE_ID).replace("__CORE__", env.PUBLIC_URL or env.CORE_URL)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/customers")
    async def customers() -> list[dict[str, str]]:
        return store.d["customers"]

    @app.post("/api/customers")
    async def new_customer(request: Request) -> dict[str, str]:
        name = str((await request.json()).get("name") or "").strip()[:60]
        return store.add_customer(name or f"Khách {len(store.d['customers']) + 1}")

    @app.get("/api/chat/{psid}")
    async def chat(psid: str) -> dict[str, Any]:
        if store.name(psid) is None:
            raise HTTPException(404, "Không có khách này")
        return {"messages": store.d["messages"].get(psid, []), "status": await status(psid)}

    @app.post("/api/send")
    async def send(request: Request) -> dict[str, str]:
        b = await request.json()
        psid, body, as_ = str(b.get("psid")), str(b.get("text") or "").strip(), b.get("as")
        if store.name(psid) is None or not body or as_ not in ("customer", "staff"):
            raise HTTPException(422, "Thiếu khách, nội dung, hoặc vai gửi")
        mid = f"mid.local{secrets.token_hex(6)}"
        # staff = echo từ hộp thư Page, không app_id (bridge thật coi là nhân viên)
        await ingest([event(mid, body, as_, psid, name=store.name(psid) if as_ == "customer" else None)])
        store.add_message(psid, as_, body)
        return {"id": mid}

    @app.post("/api/rewind")
    async def api_rewind(request: Request) -> dict[str, Any]:
        b = await request.json()
        if b.get("hours") not in REWIND_CHOICES or store.name(str(b.get("psid"))) is None:
            raise HTTPException(422, f"hours phải thuộc {sorted(REWIND_CHOICES)}")
        return {"rewound_h": b["hours"], "rows": await rewind(str(b["psid"]), b["hours"])}

    @app.post("/api/tick")
    async def api_tick() -> dict[str, Any]:
        return await tick()

    async def echo(mid: str, psid: str, body: str) -> None:
        await asyncio.sleep(0.3)  # để worker chốt xong giao dịch của nó trước
        try:  # như bridge Messenger thật: echo mang app_id của chính app -> role bot, meta echo_app=own
            await ingest([event(mid, body, "bot", psid, meta={"echo_app": "own"})])
        except Exception:
            log.exception("echo của tin đi bị lỗi")

    @app.post("/actions")
    async def actions(request: Request) -> dict[str, Any]:
        raw = await request.body()
        try:
            ts = int(request.headers.get("X-Cortex-Timestamp", ""))
        except ValueError:
            raise HTTPException(401, "invalid signature") from None
        if not verify(secret, ts, raw, request.headers.get("X-Cortex-Signature", ""),
                      now=datetime.now(UTC), max_skew_s=300):
            raise HTTPException(401, "invalid signature")
        a = json.loads(raw)
        if a.get("format") != "cortex.action/1" or not a.get("action_id"):
            raise HTTPException(400, "bad action")
        if a["action_id"] in store.d["actions"]:  # idempotent theo action_id
            return store.d["actions"][a["action_id"]]
        psid = a["conversation"]["external_id"]
        if store.name(psid) is None:
            store.add_customer(psid, psid)
        shown = (a.get("text") or "") + (f"\n— {a['disclosure']}" if a.get("disclosure") else "")
        mid = f"mid.local{secrets.token_hex(6)}"
        store.add_message(psid, "cortex", shown, actor=a.get("actor"), disclosure=a.get("disclosure"),
                          window=(a.get("window") or {}).get("basis"))
        out = {"status": "sent", "external_message_id": mid}
        store.d["actions"][a["action_id"]] = out
        store.save()
        task = asyncio.create_task(echo(mid, psid, shown))
        box.setdefault("tasks", set()).add(task)
        task.add_done_callback(box["tasks"].discard)
        return out

    return app
