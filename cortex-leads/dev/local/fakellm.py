"""LLM giả cục bộ (không mạng, không key): đúng shape runner chờ (customer_run.py).
Lượt 1 gọi lookup_catalog; lượt 2 trả JSON nháp có claims lấy từ kết quả công cụ."""
import csv
import json
import re
from typing import Any

from cortex_leads.guard.validator import extract_numbers
from cortex_leads.llm.types import LLMResult, ToolCall
from dev.local import env

_CUSTOMER = re.compile(r"^\[m\d+ customer [^\]]*\]\s*(.*)$", re.MULTILINE)
_SKIP = re.compile(r"giảm giá|khiếu nại|đã chuyển khoản|đã đăng ký|đã mua|không cần nữa", re.IGNORECASE)
_STOP = {"khóa", "tháng", "cơ", "bản"}
_TURN = "Khách vừa nhắn xong lượt này"  # dòng context_builder thêm cho lượt khách (WP16)
_HANDOFF = re.compile(r"giảm giá|khiếu nại|bớt|gặp người|quản lý", re.IGNORECASE)
_ACK = re.compile(r"^(ok|oke|okie|dạ|vâng|ừ|cảm ơn|cám ơn|thanks|thank you)([ ,.!]+(ok|oke|shop|ạ|nhé|nha|bạn|em|cảm ơn|cám ơn|nhiều))*[ .!]*$", re.IGNORECASE)
_HELLO = re.compile(r"^(xin chào|chào|hello|hi|alo|helo)\b", re.IGNORECASE)
_ASK_PRICE = re.compile(r"giá|bao nhiêu|học phí|khai giảng|lịch|bao lâu", re.IGNORECASE)


def _catalog() -> list[dict[str, str]]:
    path = env.ROOT / "dev/samples/catalog.csv"
    return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))


def _last_customer_text(messages: list[dict[str, Any]]) -> str:
    users = [m for m in messages if m.get("role") == "user"]
    found = _CUSTOMER.findall(str(users[-1].get("content", ""))) if users else []
    return found[-1] if found else ""


def _pick_code(customer_text: str) -> str:
    rows, low = _catalog(), customer_text.lower()
    scored = [(sum(w in low for w in r["name"].lower().split() if len(w) >= 4 and w not in _STOP),
               r["code"]) for r in rows]
    best = max(scored, key=lambda x: x[0], default=(0, "KH01"))
    return best[1] if best[0] else (rows[0]["code"] if rows else "KH01")


def _vnd(n: float) -> str:
    return f"{int(n):,}".replace(",", ".") + "đ"


def _turn_decision(cust: str) -> dict[str, Any] | None:
    """Lượt khách không cần tra catalog: trả JSON luôn. None = cần tra catalog trước."""
    low = cust.strip()
    if _HANDOFF.search(low):
        return {"act": "handoff", "text": "Khách xin giảm giá hoặc cần người xử lý, nhờ anh/chị trả lời, em chưa hứa gì."}
    if _ACK.match(low) or not low:
        return {"act": "none"}
    if re.fullmatch(r"(cho (em|mình|tôi|anh|chị) hỏi|mình hỏi|em hỏi)[ .…]*", low, re.IGNORECASE):
        return {"act": "wait"}
    if _ASK_PRICE.search(low):
        return None
    ask = "mình đang quan tâm khoá nào bên em để em tư vấn đúng cho mình ạ?"
    return {"act": "reply", "reason_code": "khong_ro", "claims": [],
            "text": ("Dạ em chào anh/chị ạ, " if _HELLO.match(low) else "Dạ anh/chị ơi, ") + ask}


class LocalFakeProvider:
    """complete(messages, tools=..., model=...) giống OpenAICompatibleProvider."""

    async def complete(self, messages: list[dict[str, Any]], *, tools: list[dict] | None = None,
                       model: str | None = None) -> LLMResult:
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        turn = any(_TURN in str(m.get("content", "")) for m in messages if m.get("role") == "user")
        if not tool_msgs:
            cust = _last_customer_text(messages)
            if turn and (decided := _turn_decision(cust)) is not None:
                return LLMResult(json.dumps(decided, ensure_ascii=False), tokens_in=50, tokens_out=20,
                                 model="local-fake")
            if _SKIP.search(cust) or not cust:
                return LLMResult(json.dumps({"act": "none", "reason_code": "khong_ro"}),
                                 tokens_in=50, tokens_out=5, model="local-fake")
            call = ToolCall("call_1", "lookup_catalog", {"query": _pick_code(cust)})
            return LLMResult(None, [call], tokens_in=50, tokens_out=5, model="local-fake")
        try:
            data = json.loads(str(tool_msgs[-1]["content"]))
            item = data["data"]["items"][0]
        except (ValueError, KeyError, IndexError, TypeError):
            return LLMResult(json.dumps({"act": "none", "reason_code": "khong_ro"}),
                             tokens_in=80, tokens_out=5, model="local-fake")
        code, text_ = item["code"], f"Dạ chị, {item['name']} bên em giá {_vnd(item['price'])}"
        claims: list[dict[str, Any]] = [{"value": item["price"], "source_id": code}]
        if kg := (item.get("attrs") or {}).get("khai_giang"):
            text_ += f", khai giảng {kg}"
            claims.append({"value": kg, "source_id": code})
        text_ += ", chị cần em tư vấn thêm không ạ?"
        claims += [{"value": mt.span, "source_id": code}  # "3 tháng" trong tên khoá cũng là số liệu
                   for mt in extract_numbers(item["name"]) if mt.kind == "duration"]
        out = {"act": "reply" if turn else "draft", "reason_code": "khong_ro", "has_new_info": True,
               "claims": claims, "text": text_}
        return LLMResult(json.dumps(out, ensure_ascii=False), tokens_in=120, tokens_out=40,
                         model="local-fake")
