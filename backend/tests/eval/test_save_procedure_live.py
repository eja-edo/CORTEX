"""`save_procedure` — đường ghi trực tiếp, LLM thật, DB thật, embedding thật.

Trả lời đúng câu hỏi bị treo từ đầu chuỗi thảo luận dẫn tới tính năng này:
*người dùng dạy một quy trình lặp lại (không nhất thiết đúng khuôn "khi X
thì Y"), phiên sau chỉ nhắc ngắn gọn — agent có áp dụng đúng không, và nó
có nhận ra được cách diễn đạt khác khuôn mẫu không?*

Không assert theo tên tool được gọi làm sự thật cứng duy nhất — `mode`
("created"/"updated") của `save_procedure` không lộ ra qua `tool_calls`
(chỉ có tên tool), nên sự thật cứng ở đây là đọc thẳng bảng `procedures`
sau mỗi lượt, cùng triết lý `test_procedure_live.py`.

Mỗi kịch bản chạy **một lần**, không phải phép đo phương sai — một lần đỏ
ở đây là tín hiệu để đọc transcript, không phải kết luận cuối cùng.
"""

import pytest
from sqlalchemy import text

from tests.eval.harness import EVAL_USER_ID, run_turn
from tests.eval.judge import judge

pytestmark = pytest.mark.asyncio


async def _procedures_for_user() -> list[dict]:
    """Sự thật cứng: đọc thẳng bảng `procedures`, không hỏi model."""
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT id, title, trigger_text, steps, last_confirmed_at "
                    "FROM procedures WHERE user_id = :u AND is_active IS TRUE"
                ),
                {"u": str(EVAL_USER_ID)},
            )
        ).mappings().all()
    await engine.dispose()
    return [dict(r) for r in rows]


# ── T1 — khuôn cổ điển "khi X thì Y", làm mốc so sánh ──────────────────

async def test_t1_classic_phrasing_gets_saved(eval_user):
    r = await run_turn(
        "Khi tôi có buổi họp khách hàng thì tôi luôn làm ba việc: ghi chú "
        "lại yêu cầu của khách, tạo task follow-up trong 2 ngày, và gửi "
        "email cảm ơn sau buổi họp."
    )
    print(f"\n[T1] {r!r}")

    rows = await _procedures_for_user()
    print(f"[T1] procedures in DB: {[(p['title'], p['trigger_text']) for p in rows]}")

    assert rows, "khuôn cổ điển mà còn không lưu được thì mọi thứ sau vô nghĩa"
    assert rows[0]["last_confirmed_at"] is not None, "last_confirmed_at không được set lúc tạo"

    assert await judge(
        r.reply,
        "Câu trả lời báo cho người dùng biết đã LƯU LẠI quy trình này để "
        "dùng cho lần sau — không im lặng bỏ qua, không chỉ nhắc lại nội "
        "dung mà không nói gì về việc đã ghi nhớ.",
    )


# ── T2 — diễn đạt khác khuôn, không có "khi...thì" ─────────────────────

async def test_t2_non_classic_phrasing_still_gets_saved(eval_user):
    """Đây là bài test thật của việc sửa anchoring ở assistant_system.md.

    Không dùng "khi...thì" ở bất kỳ đâu trong câu — chỉ kể lại việc gì luôn
    xảy ra, đúng kiểu diễn đạt tự nhiên nhất mà hướng dẫn cũ (bám sát một
    khuôn ví dụ) có nguy cơ bỏ sót.
    """
    r = await run_turn(
        "Sáng thứ Hai nào mình cũng làm y vậy: soạn báo cáo tuần trước, "
        "gửi cho sếp, rồi đặt lịch họp team review lúc 10h."
    )
    print(f"\n[T2] {r!r}")

    rows = await _procedures_for_user()
    print(f"[T2] procedures in DB: {[(p['title'], p['trigger_text']) for p in rows]}")

    assert rows, (
        "diễn đạt không theo khuôn 'khi X thì Y' không được lưu — đúng "
        "kiểu hỏng anchoring mà bản sửa prompt định chặn"
    )
    assert await judge(
        r.reply,
        "Câu trả lời báo cho người dùng biết đã LƯU LẠI quy trình này để "
        "dùng cho lần sau — không im lặng bỏ qua.",
    )


# ── T3 — dạy ở phiên A, nhắc ngắn ở phiên B, phải áp dụng đúng ─────────

async def test_t3_a_later_new_conversation_recalls_and_applies_it(eval_user):
    """Đúng kịch bản gốc mở ra toàn bộ chuỗi thảo luận: không nói lại chi
    tiết, phiên MỚI (không chia sẻ lịch sử) có tự biết phải làm gì không."""
    teach = await run_turn(
        "Từ giờ mỗi lần có khách hàng mới liên hệ, mình sẽ tạo note tóm "
        "tắt nhu cầu của họ, rồi tạo task nhắc follow-up trong 3 ngày."
    )
    print(f"\n[T3-teach] {teach!r}")

    rows = await _procedures_for_user()
    assert rows, "bước dạy phải lưu được thì bước nhắc lại mới có gì để kiểm"

    # Hội thoại MỚI HOÀN TOÀN — conversation_id=None, không còn tin nhắn
    # cũ nào để dựa vào. Đây là điểm khác biệt với test_procedure_live.py
    # (P3 ở đó dùng lại một quy trình đã seed sẵn qua service, không qua
    # đúng đường ghi sống); ở đây cả ghi lẫn đọc đều là đường thật.
    later = await run_turn("Mình vừa có một khách hàng mới liên hệ.")
    print(f"\n[T3-recall] {later!r}")

    assert await judge(
        later.reply,
        "Câu trả lời cho thấy hệ thống đã biết sẵn quy trình xử lý khách "
        "hàng mới của người dùng (tạo note tóm tắt nhu cầu, tạo task "
        "follow-up trong 3 ngày) — ví dụ bằng cách đề xuất thực hiện các "
        "bước đó hoặc hỏi có muốn làm luôn không — thay vì trả lời chung "
        "chung như thể chưa từng biết gì về quy trình này.",
    )


# ── T4 — dạy lại, diễn đạt khác chút, không được nhân bản ──────────────

async def test_t4_retaught_with_a_paraphrase_updates_not_duplicates(eval_user):
    first = await run_turn(
        "Khi tôi remote thì tôi phải daily trước 9h sáng và check-in trên web."
    )
    print(f"\n[T4-first] {first!r}")
    rows_after_first = await _procedures_for_user()
    assert rows_after_first, "lượt đầu phải lưu được"

    second = await run_turn(
        "À mình nói lại cho rõ: hôm nào remote thì mình daily trước 9h "
        "sáng, check-in trên web, xong thêm bước sync với team lúc 4h chiều."
    )
    print(f"\n[T4-second] {second!r}")
    rows_after_second = await _procedures_for_user()
    print(f"[T4] rows: {[(p['title'], p['trigger_text']) for p in rows_after_second]}")

    assert len(rows_after_second) <= len(rows_after_first), (
        f"dạy lại cùng hoàn cảnh (diễn đạt khác chút) tạo thêm bản ghi thay "
        f"vì cập nhật: {len(rows_after_first)} -> {len(rows_after_second)}"
    )
