"""Zero-token draft validator (DESIGN A7). Runs inside draft_followup, so the LLM cannot skip it.

Every money amount / percentage / duration / date written in the draft must match a claim, and every
claim must point at an active, unexpired catalog item whose price or attrs hold that exact value."""
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cortex_leads.core.envelope import BlockedCode, Violation
from cortex_leads.db.models import CatalogItem

_CUR = r"(?:đ|₫|vnđ|vnd|đồng|dong)(?!\w)"
_DEC = r"\d+(?:[.,]\d+)?"
_PHONE = r"(?<![\d.,])(?:\+84|0)(?:[ .\-]?\d){9}(?!\d)"
_TOKEN = re.compile(
    rf"(?P<phone>{_PHONE})"
    rf"|(?P<trd>(?P<trd_a>\d+)\s*(?:tr|triệu)(?P<trd_b>\d{{1,3}})(?!\d))"  # 2tr5
    rf"|(?P<tr>(?P<tr_a>{_DEC})\s*(?:triệu|trieu|tr|củ)(?!\w)(?P<half>\s*rưỡi)?)"  # 2,5 triệu
    rf"|(?P<k>(?P<k_a>{_DEC})\s*(?:k|nghìn|nghin|ngàn|ngan)(?!\w))"  # 500k
    rf"|(?P<pct>(?P<pct_a>{_DEC})\s*(?:%|phần trăm|phan tram))"  # 30%
    rf"|(?P<dur>(?P<dur_a>\d+)\s*(?:tháng|tuần|buổi|năm)(?!\w))"  # 3 tháng
    rf"|(?P<grp>\d{{1,3}}(?:[.,]\d{{3}})+(?!\d)(?:\s*{_CUR})?)"  # 2.500.000đ
    rf"|(?P<big>\d{{4,}}(?:\s*{_CUR})?)",  # 2500000
    re.IGNORECASE,
)


# dd/mm[/yyyy], dd-mm, "ngày dd tháng mm". Not hh:mm, not "3-6 tháng" / "2-3 buổi" ranges (R38).
_DATE = re.compile(
    r"(?<![\d/.:\-])(?:ngày\s*(?P<d2>\d{1,2})\s*tháng\s*(?P<m2>\d{1,2})"
    r"|(?P<d>\d{1,2})\s?[/\-]\s?(?P<m>\d{1,2})(?:\s?[/\-]\s?\d{2,4})?)"
    r"(?![\d:/]|\s?(?:tháng|tuần|buổi|năm|ngày|giờ|phút|người|bạn|lần|%|k\b|tr\b|triệu))",
    re.IGNORECASE)
# Clock times: 19:00, 19h30, "7 giờ tối". A bare "2h" / "3 giờ" is a duration, never scanned (WP18).
_TIME = re.compile(
    r"(?<![\d/.])(?:(?P<h1>\d{1,2})\s?(?::|h)\s?(?P<m1>[0-5]\d)"
    r"|(?P<h2>\d{1,2})\s?(?:giờ|h)\s?(?P<per>sáng|trưa|chiều|tối|đêm)(?!\w))(?!\d)", re.IGNORECASE)
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"']+", re.IGNORECASE)
_ALTS = ("phone", "trd", "tr", "k", "pct", "dur", "grp", "big")


@dataclass(frozen=True)
class Mention:
    kind: str  # money | percent | duration
    value: Decimal
    span: str


_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]+")  # kana, hanzi, hangul


def scan_dates(text: str) -> tuple[list[tuple[str, str]], str]:
    """([(dd/mm, span)], text with phones and dates blanked). Out-of-range day or month is not a date."""
    found: list[tuple[str, str]] = []

    def take(m: re.Match[str]) -> str:
        d, mo = int(m.group("d") or m.group("d2")), int(m.group("m") or m.group("m2"))
        if not (1 <= d <= 31 and 1 <= mo <= 12):
            return m.group(0)
        found.append((f"{d:02d}/{mo:02d}", m.group(0).strip()))
        return " "
    return found, _DATE.sub(take, re.sub(_PHONE, " ", text))


def scan_times(text: str) -> tuple[list[tuple[str, str]], str]:
    """([("HH:MM", span)], text with the times blanked). 19h and "7 giờ tối" both read 19:00."""
    found: list[tuple[str, str]] = []

    def take(m: re.Match[str]) -> str:
        h, mi = int(m.group("h1") or m.group("h2")), int(m.group("m1") or 0)
        per = (m.group("per") or "").casefold()
        if per in ("chiều", "tối") and h < 12 or per == "đêm" and 8 <= h <= 11:
            h += 12
        if not (0 <= h <= 23):
            return m.group(0)
        found.append((f"{h:02d}:{mi:02d}", m.group(0).strip()))
        return " "
    return found, _TIME.sub(take, text)


def _attr_times(v: Any) -> set[str]:
    if isinstance(v, str):
        return {t for t, _ in scan_times(v)[0]}
    return {t for x in v for t in _attr_times(x)} if isinstance(v, list | tuple) else set()


def _urls(text: str) -> list[str]:
    return [u.rstrip(".,;:!?)").rstrip("/").casefold() for u in _URL.findall(text)]


def _attr_urls(v: Any) -> set[str]:
    if isinstance(v, str):
        return set(_urls(v))
    if isinstance(v, dict):
        v = list(v.values())
    return {u for x in v for u in _attr_urls(x)} if isinstance(v, list | tuple) else set()


def _attr_dates(v: Any) -> set[str]:
    if isinstance(v, str):
        return {d for d, _ in scan_dates(v)[0]}
    return {d for x in v for d in _attr_dates(x)} if isinstance(v, list | tuple) else set()


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def extract_numbers(text: str) -> list[Mention]:
    out: list[Mention] = []
    for m in _TOKEN.finditer(text):
        span = m.group(0).strip()
        kind = next(n for n in _ALTS if m.group(n) is not None)
        if kind == "phone":
            continue
        if kind == "trd":
            b = m.group("trd_b")
            out.append(Mention("money", int(m.group("trd_a")) * Decimal(10**6)
                               + int(b) * Decimal(10) ** (6 - len(b)), span))
        elif kind == "tr":
            v = _dec(m.group("tr_a")) * 10**6 + (500_000 if m.group("half") else 0)
            out.append(Mention("money", v, span))
        elif kind == "k":
            out.append(Mention("money", _dec(m.group("k_a")) * 1000, span))
        elif kind == "pct":
            out.append(Mention("percent", _dec(m.group("pct_a")), span))
        elif kind == "dur":
            out.append(Mention("duration", Decimal(m.group("dur_a")), span))
        else:
            digits = re.sub(r"\D", "", re.sub(rf"\s*{_CUR}", "", span, flags=re.IGNORECASE))
            out.append(Mention("money", Decimal(digits), span))
    return out


def _num(v: Any) -> Decimal | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int | float | Decimal):
        return Decimal(str(v))
    return None


def _claim_value(raw: Any) -> tuple[Decimal | None, str | None]:
    """(number, kind) of a claim value; kind is None for bare numbers."""
    n = _num(raw)
    if n is not None:
        return n, None
    if isinstance(raw, str):
        found = extract_numbers(raw)
        if len(found) == 1:
            return found[0].value, found[0].kind
        try:
            return Decimal(raw.strip().replace(",", ".")), None
        except InvalidOperation:
            return None, None
    return None, None


def _attr_numbers(attrs: dict[str, Any]) -> list[Decimal]:
    return [n for v in attrs.values() if (n := _num(v)) is not None]


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _fold(s: str) -> str:
    return unicodedata.normalize("NFC", s).casefold()


def _check_claim(claim: dict[str, Any], rows: Sequence[CatalogItem], now: datetime
                 ) -> tuple[set[tuple[Any, str]], str | None]:
    """Returns (verified (value, kind) pairs, failure reason). A date claim's value is "dd/mm"."""
    raw = claim.get("value")
    cdates = scan_dates(raw)[0] if isinstance(raw, str) else []
    ctimes = scan_times(scan_dates(raw)[1])[0] if isinstance(raw, str) else []
    value, kind = (None, "date") if cdates or ctimes else _claim_value(raw)
    if value is None and not cdates and not ctimes:
        return set(), "claim value is not a number"
    sid = str(claim.get("source_id", ""))
    matches = [r for r in rows if sid in (str(r.id), r.code)]
    if not matches:
        return set(), "source_id is not a catalog item"
    live = [r for r in matches if r.active and (r.valid_until is None or _aware(r.valid_until) > now)]
    if not live:
        return set(), "catalog item is inactive or expired"
    ok: set[tuple[Any, str]] = set()
    for r in live:
        if cdates or ctimes:
            vals = list((r.attrs or {}).values())
            have_d, have_t = set().union(set(), *(_attr_dates(v) for v in vals)), \
                set().union(set(), *(_attr_times(v) for v in vals))
            ok |= {(d, "date") for d, _ in cdates if d in have_d}
            ok |= {(t, "time") for t, _ in ctimes if t in have_t}
            continue
        if r.price is not None and Decimal(str(r.price)) == value and kind in (None, "money"):
            ok.add((value, "money"))
        if value in _attr_numbers(r.attrs or {}) and (kind != "money" or value >= 1000):
            # an amount in attrs (deposit 500.000đ) is money too; small numbers never are
            ok.update((value, k) for k in ([kind] if kind else ["percent", "duration"] + ["money"] * (value >= 1000)))
    return ok, (None if ok else "claim value does not match the catalog")


def validate_draft(
    text: str,
    claims: Sequence[dict[str, Any]],
    catalog_rows: Sequence[CatalogItem],
    *,
    never_say: Sequence[str],
    touches: int,
    max_touches: int,
    opted_out: bool,
    has_new_info: bool,
    now: datetime,
) -> list[Violation]:
    v: list[Violation] = []
    if opted_out:
        v.append(Violation(code=BlockedCode.OPTED_OUT))
    if touches >= max_touches:
        v.append(Violation(code=BlockedCode.TOUCH_LIMIT, detail=f"{touches}/{max_touches}"))
    if not has_new_info:
        v.append(Violation(code=BlockedCode.NO_NEW_INFO))
    folded = _fold(text)
    v += [Violation(code=BlockedCode.FORBIDDEN_PHRASE, span=p)
          for p in never_say if p.strip() and _fold(p) in folded]
    v += [Violation(code=BlockedCode.FORBIDDEN_PHRASE, span=x, detail="foreign_script")  # a model's Chinese leak
          for x in _CJK.findall(text)[:1]]

    verified: set[tuple[Any, str]] = set()
    for c in claims:  # a claim only vouches; one that vouches for nothing ("giáo viên Việt Nam") blocks
        verified |= _check_claim(c, catalog_rows, now)[0]  # nothing — the text scan below is the guard
    dates, plain = scan_dates(text)
    times, plain = scan_times(plain)
    for canon, span in times:  # WP18: a class time the customer will turn up for comes from a catalog row
        if (canon, "time") not in verified:
            v.append(Violation(code=BlockedCode.UNVERIFIED_CLAIM, span=span,
                               detail="time in text has no verified claim"))
    cited_urls = set().union(set(), *(_attr_urls(list((r.attrs or {}).values()))
                                      for r in catalog_rows if r.active and (r.valid_until is None
                                                                             or _aware(r.valid_until) > now)))
    for url in _urls(text):  # WP18: a link (registration form) is only ever one a business put in its catalog
        if url not in cited_urls:
            v.append(Violation(code=BlockedCode.UNVERIFIED_CLAIM, span=url,
                               detail="url in text is not on a cited catalog row"))
    for canon, span in dates:  # R38: a date the customer will act on must come from a catalog row
        if (canon, "date") not in verified:
            v.append(Violation(code=BlockedCode.UNVERIFIED_CLAIM, span=span,
                               detail="date in text has no verified claim"))
    for mention in extract_numbers(plain):
        if (mention.value, mention.kind) not in verified:
            v.append(Violation(code=BlockedCode.UNVERIFIED_CLAIM, span=mention.span,
                               detail="number in text has no verified claim"))
    return v
