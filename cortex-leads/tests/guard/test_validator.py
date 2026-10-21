from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from cortex_leads.core.envelope import BlockedCode
from cortex_leads.db.models import CatalogItem
from cortex_leads.guard.validator import extract_numbers, scan_dates, validate_draft

NOW = datetime(2026, 10, 12, 3, 0, tzinfo=UTC)


def item(**kw) -> CatalogItem:
    kw.setdefault("code", "KH01")
    kw.setdefault("price", 2_500_000)
    kw.setdefault("attrs", {})
    kw.setdefault("active", True)
    kw.setdefault("valid_until", None)
    return CatalogItem(id=uuid4(), name="x", **kw)


def run(text, claims=(), rows=(), **kw):
    args = dict(never_say=[], touches=0, max_touches=2, opted_out=False, has_new_info=True, now=NOW)
    args.update(kw)
    return validate_draft(text, list(claims), list(rows), **args)


def codes(v):
    return [x.code for x in v]


def test_extracts_vietnamese_numbers():
    got = {(m.kind, m.value) for m in extract_numbers(
        "2.500.000đ, 2,5 triệu, 2tr5, 2tr, 500k, 30%, 3 tháng, 2 triệu rưỡi, 2500000, gọi 0901234567")}
    assert got == {("money", Decimal(2_500_000)), ("money", Decimal(2_000_000)),
                   ("money", Decimal(500_000)), ("percent", Decimal(30)),
                   ("duration", Decimal(3))}
    assert len(extract_numbers("2tr5 và 2,5 triệu và 2.500.000đ")) == 3


def test_matching_claim_passes_in_any_notation():
    r = item()
    for t in ["giá 2.500.000đ", "giá 2,5 triệu", "giá 2tr5"]:
        assert run(t, [{"value": 2_500_000, "source_id": "KH01"}], [r]) == []
    assert run("giá 2tr5", [{"value": "2,5 triệu", "source_id": str(r.id)}], [r]) == []


def test_invented_price_is_unverified():
    v = run("giá chỉ 2tr", [{"value": 2_000_000, "source_id": "KH01"}], [item()])
    assert codes(v) == [BlockedCode.UNVERIFIED_CLAIM] and v[0].span == "2tr"  # the number blocks, not the claim


def test_number_without_claim_is_unverified():
    v = run("giảm 30% hôm nay", [], [item()])
    assert codes(v) == [BlockedCode.UNVERIFIED_CLAIM] and v[0].span == "30%"


def test_percent_and_duration_from_attrs():
    r = item(attrs={"discount_pct": 30, "months": 3})
    ok = [{"value": "30%", "source_id": "KH01"}, {"value": "3 tháng", "source_id": "KH01"}]
    assert run("giảm 30% cho khóa 3 tháng", ok, [r]) == []
    assert run("giảm 30%", [{"value": 30, "source_id": "KH01"}], [r]) == []
    assert codes(run("giảm 3 tháng", [{"value": "3%", "source_id": "KH01"}], [r]))  # kind differs


def test_claim_source_rules():  # a missing / inactive / expired row vouches for nothing: the number blocks
    claim = [{"value": 2_500_000, "source_id": "KH01"}]
    text = "khoá này 2.500.000đ"
    assert codes(run(text, claim, [])) == [BlockedCode.UNVERIFIED_CLAIM]
    assert codes(run(text, claim, [item(active=False)])) == [BlockedCode.UNVERIFIED_CLAIM]
    expired = item(valid_until=NOW - timedelta(days=1))
    assert codes(run(text, claim, [expired])) == [BlockedCode.UNVERIFIED_CLAIM]
    assert run(text, claim, [item(valid_until=NOW + timedelta(days=1))]) == []
    # a text claim ("giáo viên Việt Nam") verifies nothing and blocks nothing (seen live: it blocked good replies)
    assert run("x", [{"value": "abc", "source_id": "KH01"}], [item()]) == []


def test_other_blocked_codes():
    assert codes(run("hi", never_say=["Cam kết"], )) == []
    assert codes(run("Tôi CAM KẾT đỗ", never_say=["cam kết"])) == [BlockedCode.FORBIDDEN_PHRASE]
    assert codes(run("hi", touches=2, max_touches=2)) == [BlockedCode.TOUCH_LIMIT]
    assert codes(run("hi", opted_out=True)) == [BlockedCode.OPTED_OUT]
    assert codes(run("hi", has_new_info=False)) == [BlockedCode.NO_NEW_INFO]


# --- R38: dates -------------------------------------------------------------------------------
def course(**attrs):
    return item(code="IELTS-3M", price=4_500_000, attrs=attrs)


def test_date_matching_a_catalog_attr_passes_in_both_attr_shapes():
    claim = [{"value": "20/10", "source_id": "IELTS-3M"}]
    for attrs in ({"khai_giang": "khai giảng 20/10"}, {"start_dates": ["05/11", "20/10"]}):
        for text in ("Khoá khai giảng 20/10 chị nhé", "Khai giảng ngày 20 tháng 10 ạ",
                     "Lớp 20-10 còn chỗ", "Khai giảng 20/10/2026 nha"):
            assert run(text, claim, [course(**attrs)]) == [], (attrs, text)


def test_wrong_or_unclaimed_date_is_blocked_with_its_span():
    rows = [course(khai_giang="20/10")]
    wrong = run("Khoá khai giảng 25/10 chị nhé", [{"value": "20/10", "source_id": "IELTS-3M"}], rows)
    assert [(x.code, x.span) for x in wrong] == [(BlockedCode.UNVERIFIED_CLAIM, "25/10")]
    assert codes(run("Khoá khai giảng 20/10 chị nhé", [], rows)) == [BlockedCode.UNVERIFIED_CLAIM]
    bad_claim = run("Khai giảng 25/10", [{"value": "25/10", "source_id": "IELTS-3M"}], rows)
    assert BlockedCode.UNVERIFIED_CLAIM in codes(bad_claim)
    expired = [item(code="IELTS-3M", attrs={"khai_giang": "20/10"}, active=False)]
    assert codes(run("Khai giảng 20/10", [{"value": "20/10", "source_id": "IELTS-3M"}], expired))


def test_times_phones_and_ranges_are_not_dates():
    for text in ("Em gọi chị lúc 9:30 nha", "Chị gọi 0901 234 567 hoặc 0901-234-567 nha",
                 "Em nhắn lúc 14:05 ngày mai nha"):
        # since WP18 a clock time needs a catalog row (A7), but it is never mistaken for a date or a number
        assert [v for v in run(text) if "time" not in (v.detail or "")] == [], text
    assert scan_dates("Khoá 3-6 tháng, 2-3 buổi, 12-18 tuổi, 1-2 lần")[0] == []
    assert codes(run("Khoá 3 tháng khai giảng ngày 20 tháng 10", [
        {"value": "3 tháng", "source_id": "IELTS-3M"}, {"value": "20/10", "source_id": "IELTS-3M"}],
        [course(thang=3, khai_giang="20/10")])) == []


def test_a_foreign_script_leak_is_blocked() -> None:  # seen with a real model: "...cứ yên tâm啦."
    from datetime import UTC, datetime
    v = validate_draft("Dạ mình cứ yên tâm啦.", [], [], never_say=[], touches=0, max_touches=3,
                       opted_out=False, has_new_info=True, now=datetime.now(UTC))
    assert [(x.code.value, x.span) for x in v] == [("FORBIDDEN_PHRASE", "啦")]


# --- WP18: class times and links ----------------------------------------------------------------
SLOT = dict(code="LH-20-10", price=None, attrs={"ngay": "20/10", "gio": "19:00-20:30", "suc_chua": 6})
FORM = dict(code="PHIEU", price=None, attrs={"url": "https://tt.example.vn/dang-ky"})


def test_scan_times_forms_and_non_times():
    from cortex_leads.guard.validator import scan_times
    got = lambda t: [x for x, _ in scan_times(t)[0]]  # noqa: E731
    assert got("19:00") == ["19:00"] and got("19h30") == ["19:30"] and got("7 giờ tối") == ["19:00"]
    assert got("lúc 7 giờ sáng") == ["07:00"] and got("19:00-20:30") == ["19:00", "20:30"]
    assert got("học 2h mỗi ngày, 3 giờ tự học, ngày 20/10, 2.500.000đ") == []  # durations are not times


def test_time_in_text_needs_a_verified_claim():
    row = item(**SLOT)
    ok = run("Lớp học thử 20/10 lúc 19:00 nhé ạ", [{"value": "20/10", "source_id": "LH-20-10"},
                                                   {"value": "19:00", "source_id": "LH-20-10"}], [row])
    assert ok == []
    bad = run("Lớp học thử 20/10 lúc 20:00 nhé ạ", [{"value": "20/10", "source_id": "LH-20-10"},
                                                    {"value": "19:00", "source_id": "LH-20-10"}], [row])
    assert [(v.code, v.span) for v in bad] == [(BlockedCode.UNVERIFIED_CLAIM, "20:00")]
    assert codes(run("Lớp học lúc 19:00 ạ", [], [row])) == [BlockedCode.UNVERIFIED_CLAIM]  # no claim at all
    # "7 giờ tối" is 19:00; a range in the row vouches for both ends
    assert run("Mình vào lúc 7 giờ tối", [{"value": "19:00", "source_id": "LH-20-10"}], [row]) == []
    assert run("hết lúc 20h30", [{"value": "20:30", "source_id": "LH-20-10"}], [row]) == []


def test_url_must_be_on_a_cited_catalog_row():
    form = item(**FORM)
    assert run("Mình điền phiếu ở https://tt.example.vn/dang-ky nhé", [{"value": 1, "source_id": "PHIEU"}], [form]) == []
    assert run("Phiếu đây: https://tt.example.vn/dang-ky.", [], [form]) == []  # trailing dot, row was named
    bad = run("Mình điền phiếu ở https://tt-example.vn/dang-ky nhé", [], [form])
    assert [(v.code, v.span) for v in bad] == [(BlockedCode.UNVERIFIED_CLAIM, "https://tt-example.vn/dang-ky")]
    assert codes(run("Xem www.evil.example nhé", [], [])) == [BlockedCode.UNVERIFIED_CLAIM]
    expired = item(**FORM, valid_until=NOW - timedelta(days=1))
    assert codes(run("https://tt.example.vn/dang-ky", [], [expired])) == [BlockedCode.UNVERIFIED_CLAIM]
