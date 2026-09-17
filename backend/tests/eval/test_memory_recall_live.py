"""Bộ use case sống cho tầng bộ nhớ — LLM thật, DB thật, không mock gì.

Xếp từ đơn giản tới phức tạp; mỗi cấp giả định cấp dưới đã xanh:

    Cấp 1  không có bộ nhớ    — không bịa ra thứ chưa từng được dạy
    Cấp 2  recall một mảnh    — nhớ được, và không hỏi lại thứ đã biết
    Cấp 3  trigger sai        — nhận ra similarity ≠ relevance
    Cấp 4  nhiều mảnh         — chọn đúng mảnh liên quan giữa nhiễu
    Cấp 5  phương sai         — cùng câu hỏi, nhiều lần, lệch bao nhiêu
    Cấp 6  xuyên phiên        — hội thoại mới vẫn nhớ người dùng là ai

Chạy:  pytest -m live_llm tests/eval -v -s

Assertion đi theo hai tầng: gì kiểm được bằng sự thật trong DB (tool nào
thật sự chạy) thì kiểm cứng; phần còn lại là ngữ nghĩa nên giao cho
`judge()`. Không assert chuỗi chính xác ở đâu cả — nó đo cách hành văn
chứ không đo hành vi, và sẽ đỏ mỗi lần model đổi cách diễn đạt.
"""

import asyncio

import pytest

from tests.eval.harness import run_turn
from tests.eval.judge import judge

pytestmark = pytest.mark.asyncio

REMOTE_ROUTINE = (
    "Khi tôi remote thì phải daily trước 9h sáng, check-in trên web, "
    "và sync với team lúc 4h chiều."
)
GYM_PREFERENCE = "Tôi luôn tập gym lúc 19:00 các ngày trong tuần."
NO_LATE_MEETINGS = "Tôi không bao giờ họp sau 18h vì phải đón con."
IELTS_GOAL = "Mục tiêu của tôi là thi IELTS 7.0 vào tháng 12."


# ── Cấp 1 — Không có bộ nhớ ────────────────────────────────────────────

async def test_l1_no_memory_does_not_invent_a_routine(eval_user):
    """Kho rỗng thì phải nói là không biết, không dựng ra một quy trình.

    Kiểu hỏng đang canh: tìm kiếm vector luôn trả về hàng *gần nhất*, nên
    một hệ thống không có sàn liên quan sẽ luôn "nhớ ra" điều gì đó. Với
    kho rỗng, câu trả lời đúng duy nhất là hỏi lại.
    """
    r = await run_turn("hôm nay tôi remote")
    print(f"\n[L1] {r!r}")

    assert not r.called("create_task"), "tạo task từ hư không"
    assert await judge(
        r.reply,
        "Câu trả lời KHÔNG khẳng định người dùng có sẵn một quy trình/thói "
        "quen remote cụ thể nào (vì hệ thống chưa từng được dạy). Hỏi lại, "
        "hoặc đề nghị người dùng cho biết cần làm gì, đều là PASS.",
    )


# ── Cấp 2 — Recall một mảnh ────────────────────────────────────────────

async def test_l2_recalls_routine_without_a_tool_call(eval_user, memory_seeder):
    """Nhớ đủ ba bước — và nhớ được mà **không** cần gọi tool.

    Phần "không gọi tool" mới là thứ đang được test. Bộ nhớ giờ nằm sẵn
    trong ngữ cảnh; một lời gọi `extract_memory` ở đây trả về đúng những
    dòng đã có, muộn hơn một vòng LLM và đắt hơn ~10k token.
    """
    await memory_seeder([("routine", REMOTE_ROUTINE)])
    r = await run_turn("hôm nay tôi remote")
    print(f"\n[L2] {r!r}")

    assert r.mentions("daily"), "quên bước daily"
    assert r.mentions("check-in", "checkin", "check in"), "quên bước check-in"
    assert r.mentions("sync", "4h", "16:00"), "quên bước sync chiều"
    assert not r.called("extract_memory"), (
        "gọi lại extract_memory cho thứ đã nằm sẵn trong ngữ cảnh"
    )


async def test_l2_proposes_but_does_not_create_silently(eval_user, memory_seeder):
    """Đọc được quy trình ≠ được phép thay người dùng tạo việc."""
    await memory_seeder([("routine", REMOTE_ROUTINE)])
    r = await run_turn("hôm nay tôi remote")
    print(f"\n[L2-b] {r!r}")

    assert not r.called("create_task"), "tự tạo task khi chưa ai đồng ý"
    assert await judge(
        r.reply,
        "Câu trả lời hỏi xác nhận / đề nghị trước khi tạo việc, thay vì "
        "thông báo rằng đã tạo xong.",
    )


async def test_l2_does_not_ask_what_it_already_knows(eval_user, memory_seeder):
    """Biết rồi thì xác nhận, đừng hỏi lại từ đầu.

    Đây là thứ người dùng cảm nhận trực tiếp là "hệ thống hiểu mình":
    không bắt họ khai lại một dữ kiện họ đã khai.
    """
    await memory_seeder([("preference", GYM_PREFERENCE)])
    r = await run_turn("mai tôi đi gym")
    print(f"\n[L2-c] {r!r}")

    assert await judge(
        r.reply,
        "Câu trả lời KHÔNG hỏi trống không người dùng tập lúc mấy giờ. Nó "
        "hoặc dùng luôn 19:00, hoặc hỏi xác nhận '19:00 như mọi khi chứ?'. "
        "Hỏi một câu mở kiểu 'Bạn tập lúc mấy giờ?' là FAIL.",
    )


# ── Cấp 3 — Trigger sai ────────────────────────────────────────────────

async def test_l3_ignores_a_similar_but_irrelevant_memory(eval_user, memory_seeder):
    """Test quan trọng nhất của bộ này.

    Đo được, cùng bộ nhớ remote: `deadline dự án` đạt 0.5844, xếp **trên**
    `remote` (0.5810). Hai dải chồng nhau nên không ngưỡng số nào tách
    được — quy trình remote sẽ lọt vào ngữ cảnh của một câu nói về
    deadline, mọi lượt, và đó là hành vi đã biết chứ không phải lỗi.

    Nên phép chặn cuối cùng là ngữ nghĩa, không phải số: model phải đọc vế
    "khi tôi remote" và tự thấy nó không mô tả hoàn cảnh vừa được nêu.
    Test này kiểm đúng phép chặn đó.
    """
    await memory_seeder([("routine", REMOTE_ROUTINE)])
    r = await run_turn("deadline dự án sắp tới rồi, tôi hơi lo")
    print(f"\n[L3] {r!r}")

    assert not r.called("create_task"), "tạo task từ một quy trình không liên quan"
    assert await judge(
        r.reply,
        "Câu trả lời KHÔNG đề xuất quy trình làm-việc-từ-xa (daily trước 9h, "
        "check-in trên web, sync 4h chiều) — vì người dùng đang nói về "
        "deadline, không phải về việc remote. Nhắc tới quy trình remote ở "
        "bất kỳ dạng nào là FAIL.",
    )


# ── Cấp 4 — Nhiều mảnh, chọn đúng ──────────────────────────────────────

async def test_l4_picks_the_relevant_memory_among_noise(eval_user, memory_seeder):
    """Bốn bộ nhớ trong kho, chỉ một cái nói về chuyện đang bàn."""
    await memory_seeder([
        ("routine", REMOTE_ROUTINE),
        ("preference", GYM_PREFERENCE),
        ("constraint", NO_LATE_MEETINGS),
        ("goal", IELTS_GOAL),
    ])
    r = await run_turn("đặt lịch họp với khách lúc 19h tối mai")
    print(f"\n[L4] {r!r}")

    assert await judge(
        r.reply,
        "Câu trả lời nhận ra 19h xung đột với ràng buộc 'không họp sau 18h' "
        "của người dùng — bằng cách cảnh báo, hỏi lại, hoặc đề xuất giờ "
        "khác. Đặt lịch 19h mà không hề nhắc tới xung đột là FAIL.",
    )


# ── Cấp 5 — Phương sai giữa các lần ────────────────────────────────────

async def test_l5_same_question_three_times_is_consistent(eval_user, memory_seeder):
    """Cùng một câu, ba lần — bao nhiêu lần trả lời giống nhau về *hành vi*?

    Đây là con số mà cả P0 tồn tại để kéo xuống. Trước khi recall là mặc
    định, biến chính gây lệch là "lượt này model có nhớ gọi tool không";
    giờ bộ nhớ tới bất kể model quyết định gì, nên ba lần phải cùng nhớ ra
    ba bước và cùng không tự tạo việc.

    Chấm trên hành vi, không trên câu chữ: hai câu trả lời viết khác nhau
    mà cùng liệt kê đủ ba bước và cùng hỏi trước khi tạo thì nhất quán.
    """
    await memory_seeder([("routine", REMOTE_ROUTINE)])

    runs = []
    for _ in range(3):
        runs.append(await run_turn("hôm nay tôi remote"))

    recalled = [
        r.mentions("daily")
        and r.mentions("check-in", "checkin", "check in")
        and r.mentions("sync", "4h", "16:00")
        for r in runs
    ]
    created = [r.called("create_task") for r in runs]

    for i, r in enumerate(runs):
        print(f"\n[L5 run {i+1}] recall={recalled[i]} create={created[i]} {r!r}")

    assert all(recalled), f"recall không ổn định giữa các lần: {recalled}"
    assert not any(created), f"có lần tự tạo task: {created}"


# ── Cấp 6 — Xuyên phiên ────────────────────────────────────────────────

async def test_l6_a_brand_new_conversation_still_knows_the_user(eval_user, memory_seeder):
    """Hai hội thoại tách rời, không chia sẻ một tin nhắn nào.

    Đây là hình dạng thật của lời than "phiên này hiểu mình, phiên kia thì
    không": cửa sổ tin nhắn gần không với tới hội thoại trước, nên nếu bộ
    nhớ dài hạn không tự tới, phiên mới bắt đầu như với người lạ.

    Không truyền `conversation_id` → `handle()` mở hội thoại mới, đúng như
    người dùng mở một cuộc trò chuyện mới trong app.
    """
    await memory_seeder([("routine", REMOTE_ROUTINE), ("constraint", NO_LATE_MEETINGS)])

    first = await run_turn("chào bạn")
    second = await run_turn("hôm nay tôi remote")  # hội thoại KHÁC

    print(f"\n[L6 phiên 1] conv={first.conversation_id}")
    print(f"[L6 phiên 2] conv={second.conversation_id} {second!r}")

    assert first.conversation_id != second.conversation_id, (
        "hai lượt rơi vào cùng một hội thoại — test không kiểm được điều nó định kiểm"
    )
    assert second.mentions("daily"), "phiên mới không nhớ quy trình"
    assert await judge(
        second.reply,
        "Câu trả lời cho thấy hệ thống đã biết sẵn quy trình remote của "
        "người dùng (liệt kê được các bước), thay vì hỏi người dùng quy "
        "trình đó là gì.",
    )
