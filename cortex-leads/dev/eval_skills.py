"""Chạy bộ eval giọng trả lời (WP15) qua run_job thật: runner + validator + skill.

    python -m dev.eval_skills --provider fake                       # kiểm đường ống, không gọi LLM
    python -m dev.eval_skills --provider env --env-file data/llm-x.env --out data/eval/x.md

Dùng DB riêng (CL_DATABASE_URL...); mỗi case một tenant mới. Báo cáo in ĐẦY ĐỦ từng nháp: đọc quan trọng
hơn điểm số (LESSONS). Điểm tự động chỉ để bắt lỗi hiển nhiên."""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
CARE = ROOT / "sandboxes" / "customer_care"
NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)  # 10:00 giờ Việt Nam
EVENTS = {"hoi-lai-khach-im": "conversation.silent", "hoi-lai-dung-hen": "conversation.promised_date_reached",
          "tra-loi-khach": "conversation.awaiting_reply"}


def load_env(path: Path, *, override: bool) -> None:
    for line in path.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            k, _, v = line.partition("=")
            if override or k.strip() not in os.environ:
                os.environ[k.strip()] = v.strip()


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.casefold().replace("đ", "d"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def mentions(text: str, ref: str) -> bool:
    """Khớp mềm, bỏ dấu: đủ ít nhất 60% từ của `ref` xuất hiện trong nháp."""
    words = re.findall(r"\w+", fold(ref))
    body = set(re.findall(r"\w+", fold(text)))
    return bool(words) and sum(w in body for w in words) / len(words) >= 0.6


def fake_reply(case: dict[str, Any]) -> str:
    e = case["expect"]
    turn = case["skill"] == "tra-loi-khach"  # WP16: acts are reply | wait | handoff | none
    if turn and e.get("wait"):
        return json.dumps({"act": "wait"})
    if turn and e.get("handoff"):
        return json.dumps({"act": "handoff", "text": "Khách cần người trả lời, nhờ anh/chị xem giúp, em chưa hứa gì."},
                          ensure_ascii=False)
    if e["act"] == "none":
        return json.dumps({"act": "none", "reason_code": e.get("reason_code", "khong_ro")})
    ref = " ".join(e.get("must_reference") or ["chuyện hôm trước"])
    pron = "bạn" if "bạn" in ref or any("bạn" in t["text"] for t in case["conversation"]) else "chị"
    return json.dumps({"act": "reply" if turn else "draft", "reason_code": e.get("reason_code", "khong_ro"),
                       "has_new_info": True,
                       "claims": [], "text": f"Dạ {pron}, em nhắn lại về {ref} nha, {pron} cần em hỗ trợ gì thêm không ạ?"},
                      ensure_ascii=False)


async def run_case(case: dict[str, Any], provider_factory) -> dict[str, Any]:
    from cortex_leads.config import get_settings
    from cortex_leads.core.ids import new_connector_id, uuid7
    from cortex_leads.db import models as m
    from cortex_leads.db.session import system_session, tenant_session
    from cortex_leads.domain.pack import load_pack_file
    from cortex_leads.llm.gateway import LLMGateway
    from cortex_leads.runner.customer_run import run_job
    from cortex_leads.skills.loader import sync_dir
    from cortex_leads.skills.registry import promote
    from cortex_leads.tools.registry import default_registry
    from cortex_leads.triggers.engine import on_conversation_event

    tid, sid, cid = uuid7(), uuid7(), new_connector_id()
    async with system_session() as s:
        s.add(m.Tenant(id=tid, name=f"eval-{case['id']}"))
    async with tenant_session(tid) as s:
        s.add(m.Sandbox(id=sid, tenant_id=tid, name="customer_care", profile_ref="customer_drafter@1",
                        domain_pack=load_pack_file(CARE / "domain.yaml").model_dump(mode="json"),
                        budget={"runs_per_day": 100, "drafts_per_staff_per_day": 20, "tokens_per_day": 100000},
                        business_hours={"start": "00:00", "end": "23:59"}))
        for it in case.get("catalog", []):
            s.add(m.CatalogItem(tenant_id=tid, **it))
    async with system_session() as s:
        s.add(m.Connector(id=cid, tenant_id=tid, sandbox_id=sid, channel_kind="messenger", trust="official",
                          secret_enc=Fernet(get_settings().CONNECTOR_SECRET_KEY).encrypt(b"eval")))
    msgs = case["conversation"]
    last_c = max((x for x in msgs if x["role"] == "customer"), key=lambda x: x["at"])
    last_s = max((x for x in msgs if x["role"] == "staff"), key=lambda x: x["at"], default=None)
    at = lambda x: NOW + timedelta(hours=x["at"])
    async with tenant_session(tid) as s:
        contact = m.Contact(tenant_id=tid, connector_id=cid, external_id="c1", display_name="Khách Eval")
        s.add(contact)
        await s.flush()
        conv = m.Conversation(
            tenant_id=tid, sandbox_id=sid, connector_id=cid, external_id="conv", contact_id=contact.id,
            channel_kind="messenger", intent="hoi_gia", touches=case.get("touches", 0),
            last_customer_at=at(last_c), last_customer_msg_id="m-last",
            last_staff_at=at(last_s) if last_s else None,
            promised_date=NOW.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date() if case.get("promised_today") else None)
        s.add(conv)
        await s.flush()
        for i, x in enumerate(msgs):
            s.add(m.Message(tenant_id=tid, conversation_id=conv.id, connector_id=cid, external_id=f"e{i}",
                            sender_role=x["role"], text=x["text"], occurred_at=at(x)))
        rows = await sync_dir(s, tid, sid, CARE / "skills")
        sv = next(r for r in rows if r.name == case["skill"])
        for st in ("shadow", "live"):
            await promote(s, sid, sv.name, sv.version, st)
        never_say = sv.manifest.get("never_say", [])
    gw = LLMGateway(provider_factory(case), retry_delay_s=0)
    out: dict[str, Any] = {"id": case["id"], "never_say": never_say}
    t0 = time.perf_counter()
    async with tenant_session(tid) as s:
        conv = await s.get(m.Conversation, conv.id)
        jobs = await on_conversation_event(s, conv, EVENTS[case["skill"]], NOW)
        if not jobs:
            return {**out, "act": "no_job", "text": None, "blocked": [], "tokens": (0, 0), "secs": 0.0}
        run = await run_job(s, jobs[0], gw, default_registry(clock=lambda: NOW), NOW)
        draft = (await s.execute(select(m.Draft).where(m.Draft.run_id == run.id))).scalars().first()
        waits = (await s.get(m.Conversation, conv.id)).reply_waits
    out |= {"act": run.act or run.status, "reason": run.reason_code, "blocked": list(run.blocked_codes),
            "text": draft.text if draft else None, "claims": draft.claims if draft else [],
            "tokens": (run.tokens_in, run.tokens_out), "secs": time.perf_counter() - t0, "status": run.status,
            "handoff": bool(draft and draft.needs_human), "wait": waits > 0}
    return out


def score(case: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    e, text = case["expect"], r.get("text") or ""
    act = "draft" if r["act"] == "draft" else "none" if r["act"] == "none" else r["act"]
    banned = [p for p in r["never_say"] if fold(p) in fold(text)]
    s = {"act_ok": act == e["act"], "banned": banned,
         "forbidden_blocked": "FORBIDDEN_PHRASE" in r["blocked"], "words": len(text.split())}
    s["reason_ok"] = None if "reason_code" not in e else r.get("reason") == e["reason_code"]
    s["ref_ok"] = None if not (e.get("must_reference") and text) else all(mentions(text, x) for x in e["must_reference"])
    s["len_ok"] = None if not (e.get("max_words") and text) else s["words"] <= e["max_words"]
    s["not_ok"] = None if not (e.get("must_not") and text) else not any(x in text for x in e["must_not"])
    for key in ("handoff", "wait"):  # WP16 turn cases only
        s[f"{key}_ok"] = None if key not in e else r.get(key) == e[key]
    checks = [v for k, v in s.items() if k.endswith("_ok") and v is not None]
    s["pass"] = all(checks) and not banned and not s["forbidden_blocked"]
    return s


def report(cases, results, scores, provider: str, price: tuple[float, float]) -> str:
    n, ok = len(cases), sum(s["pass"] for s in scores)
    tin = sum(r["tokens"][0] for r in results)
    tout = sum(r["tokens"][1] for r in results)
    cost = (tin * price[0] + tout * price[1]) / 1e6
    mark = lambda v: "-" if v is None else ("ok" if v else "SAI")
    lines = [f"# Eval giọng trả lời ({provider})", "",
             f"{ok}/{n} case đạt tự động. Token vào/ra: {tin}/{tout}, chi phí ước tính ${cost:.4f} "
             f"(giá/1M token: vào {price[0]}, ra {price[1]}). Chấm tự động chỉ bắt lỗi hiển nhiên; hãy đọc từng nháp.", "",
             "| case | act | reason | tham chiếu | độ dài | cụm cấm | số từ | trễ(s) | đạt |", "|---|---|---|---|---|---|---|---|---|"]
    for c, r, s in zip(cases, results, scores, strict=True):
        ban = len(s["banned"]) + (1 if s["forbidden_blocked"] and not s["banned"] else 0)
        lines.append(f"| {c['id']} | {mark(s['act_ok'])} | {mark(s['reason_ok'])} | {mark(s['ref_ok'])} | "
                     f"{mark(s['len_ok'])} | {ban} | {s['words']} | {r['secs']:.1f} | {'V' if s['pass'] else 'X'} |")
    lines += ["", "## Từng case", ""]
    for c, r, s in zip(cases, results, scores, strict=True):
        lines += [f"### {c['id']} ({c['skill']}, touches={c.get('touches', 0)})", "", "Hội thoại:"]
        lines += [f"- {x['role']} ({x['at']}h): {x['text']}" for x in c["conversation"]]
        lines += ["", f"Kỳ vọng: `{json.dumps(c['expect'], ensure_ascii=False)}`",
                  f"Kết quả: act={r['act']}, reason_code={r.get('reason')}, validator chặn={r['blocked'] or 'không'}",
                  f"Cụm cấm trong nháp: {s['banned'] or 'không'}", ""]
        lines += [f"> {r['text']}" if r.get("text") else "> (không có nháp)", ""]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["fake", "env"], default="fake")
    ap.add_argument("--env-file", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cases", type=Path, default=CARE / "eval" / "cases.yaml")
    ap.add_argument("--price-in", type=float, default=0.15, help="USD / 1M token vào (ước tính)")
    ap.add_argument("--price-out", type=float, default=0.60, help="USD / 1M token ra (ước tính)")
    a = ap.parse_args(argv)
    if a.env_file:
        load_env(a.env_file, override=True)
    load_env(ROOT / ".env.test", override=False)  # DB + khoá test nếu chưa có
    from cortex_leads.config import get_settings

    get_settings.cache_clear()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")  # alembic tự chạy event loop: gọi trước asyncio.run
    asyncio.run(evaluate(a))
    return 0


async def evaluate(a: argparse.Namespace) -> None:
    from cortex_leads.llm.providers import FakeProvider, OpenAICompatibleProvider
    from cortex_leads.llm.types import LLMResult
    from cortex_leads.skills.loader import load_yaml

    cases = load_yaml(a.cases.read_text(encoding="utf-8"))["cases"]
    real = OpenAICompatibleProvider() if a.provider == "env" else None

    def provider_for(case):
        return real or FakeProvider([LLMResult(content=fake_reply(case), tokens_in=600, tokens_out=60, model="fake")])

    results = [await run_case(c, provider_for) for c in cases]
    scores = [score(c, r) for c, r in zip(cases, results, strict=True)]
    md = report(cases, results, scores, a.provider, (a.price_in, a.price_out))
    out = a.out or ROOT / "data" / "eval" / f"{datetime.now():%Y%m%d-%H%M%S}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md.split("\n\n")[1])
    print(f"Báo cáo: {out}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
