"""Quy trình có trạng thái — LLM thật, DB thật.

Câu hỏi mà cả P1 sinh ra để trả lời: *"khi người dùng nhắc lại hoàn cảnh,
hệ thống có biết còn bước nào phải làm không?"* Bộ nhớ dạng câu văn không
trả lời được — nó chỉ đọc lại nguyên danh sách, mỗi lần như mọi lần.

Bậc thang, mỗi cấp giả định cấp dưới xanh:

    P1  quy trình được nhận ra    — nhắc hoàn cảnh thì thấy đúng quy trình
    P2  báo xong thì tiến độ đổi  — agent gọi mark_procedure_step
    P3  nhắc lại thì nhớ          — không đọc lại bước đã xong
    P4  hoàn cảnh khác thì im     — không lôi quy trình ra khi không liên quan
"""

import pytest
from sqlalchemy import text

from tests.eval.harness import EVAL_USER_ID, run_turn
from tests.eval.judge import judge

pytestmark = pytest.mark.asyncio

TRIGGER = "remote, làm việc từ xa, làm ở nhà, wfh"
STEPS = [
    {"title": "Daily", "due_hint": "trước 9h sáng"},
    {"title": "Check-in trên web"},
    {"title": "Sync với team", "due_hint": "4h chiều"},
]


@pytest.fixture
def procedure_seeder(eval_user):
    """Nạp một quy trình qua đường ghi thật (embedding thật cho từng cách nói)."""

    async def _seed():
        from app.database_async import make_async_sessionmaker
        from app.services.procedures import ProcedureService

        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            await db.execute(
                text("DELETE FROM procedures WHERE user_id = :u"),
                {"u": str(EVAL_USER_ID)},
            )
            await db.commit()
            procedure = await ProcedureService(db).create(
                user_id=EVAL_USER_ID,
                title="Quy trình làm việc từ xa",
                trigger_text=TRIGGER,
                steps=STEPS,
            )
            await db.commit()
            pid = procedure.id
        await engine.dispose()
        return pid

    return _seed


async def _mark_done(procedure_id, order: int):
    """Đánh dấu một bước qua service, không qua model."""
    from app.database_async import make_async_sessionmaker
    from app.services.procedures import STEP_DONE, ProcedureService

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        service = ProcedureService(db)
        run = await service.get_active_run(procedure_id)
        assert run is not None, "chưa có run nào đang mở để đánh dấu"
        await service.mark_step(run, order, STEP_DONE)
        await db.commit()
    await engine.dispose()


async def _run_state(procedure_id):
    """Trạng thái thật trong DB — không hỏi model, đọc thẳng."""
    from app.database_async import make_async_sessionmaker
    from app.services.procedures import ProcedureService

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        run = await ProcedureService(db).get_active_run(procedure_id)
        states = list(run.step_states) if run else []
    await engine.dispose()
    return states


# ── P1 — quy trình được nhận ra ────────────────────────────────────────

async def test_p1_mentioning_the_situation_surfaces_the_procedure(procedure_seeder):
    """Nhắc hoàn cảnh thì thấy quy trình — nhưng đừng chấm theo từng chữ.

    Bản đầu của test này assert cứng rằng câu trả lời phải chứa "daily", và
    nó **phạt model vì đã đúng**: chạy lúc 5h chiều, model bỏ bước "Daily
    trước 9h sáng" ra khỏi danh sách việc còn phải làm. Đó là hành vi tốt,
    không phải hồi quy. Cái đáng kiểm là quy trình có được nhận ra và các
    bước còn lại có được nói ra hay không.
    """
    await procedure_seeder()
    r = await run_turn("hôm nay tôi remote")
    print(f"\n[P1] {r!r}")

    assert r.mentions("check-in", "checkin", "check in", "sync"), (
        "không nhắc bước nào của quy trình"
    )
    assert await judge(
        r.reply,
        "Câu trả lời cho thấy hệ thống đã biết sẵn quy trình làm việc từ xa "
        "của người dùng và nói ra các bước cần làm, thay vì hỏi người dùng "
        "quy trình đó gồm những gì.",
    )


async def test_p1_a_different_phrasing_still_matches(procedure_seeder):
    """Cách nói khác vẫn phải khớp — đây là lý do mỗi cách nói có embedding riêng.

    Đo được: với trigger gộp một chuỗi, "mai tôi làm ở nhà" chỉ đạt 0.5464
    và trượt hẳn. Tách hàng thì lên 0.7683.
    """
    await procedure_seeder()
    r = await run_turn("mai tôi làm ở nhà")
    print(f"\n[P1-b] {r!r}")

    assert await judge(
        r.reply,
        "Câu trả lời nhắc tới quy trình làm việc từ xa của người dùng (các "
        "bước như daily, check-in trên web, sync với team) — nghĩa là hệ "
        'thống nhận ra "làm ở nhà" chính là hoàn cảnh remote của họ. Câu '
        "trả lời không liên quan gì tới quy trình đó là FAIL.",
    )


# ── P2 — báo xong thì tiến độ đổi ──────────────────────────────────────

async def test_p2_reporting_a_finished_step_updates_the_run(procedure_seeder):
    """Nửa còn lại của tính năng: tiến độ phải **ghi xuống được**.

    Kiểm bằng trạng thái trong DB, không bằng câu chữ của model: "đã ghi
    nhận" trong câu trả lời không chứng minh gì cả.
    """
    procedure_id = await procedure_seeder()
    first = await run_turn("hôm nay tôi remote")
    second = await run_turn(
        "daily xong rồi nhé", conversation_id=first.conversation_id
    )
    print(f"\n[P2] {second!r}")

    assert second.called("mark_procedure_step"), "không gọi tool cập nhật tiến độ"

    states = await _run_state(procedure_id)
    done = [s for s in states if s.get("status") == "done"]
    assert len(done) == 1, f"tiến độ không được ghi: {states}"
    assert done[0]["order"] == 1


async def test_p2_does_not_tick_a_step_the_user_never_reported(procedure_seeder):
    """Không được đánh dấu hộ người dùng — kể cả khi bước đó đã quá giờ.

    Bộ eval này ban đầu **không** bắt được lỗi đó: bốn lần chạy đều xanh
    trong khi mọi lượt đều gọi `mark_procedure_step(step_order=1,
    status="done")`, kể cả những lượt người dùng chỉ nói "mai tôi làm ở
    nhà". Thí nghiệm đối chứng mới lộ ra nguyên nhân:

        bước "Daily — trước 9h sáng", chạy lúc 21h  → model TỰ tick
        bước "Daily" (không kèm giờ)                → model không tick

    Model đọc "quá giờ" thành "đã xong" rồi ghi vào DB rằng người dùng đã
    làm một việc họ chưa hề nhắc tới. Test này là chỗ lỗi đó phải lộ ra.
    Bước 1 của quy trình mẫu cố ý mang mốc "trước 9h sáng" — chạy bất cứ
    lúc nào sau 9h là đã tái hiện đúng điều kiện.
    """
    procedure_id = await procedure_seeder()
    r = await run_turn("hôm nay tôi remote")
    print(f"\n[P2-guard] {r!r}")

    states = await _run_state(procedure_id)
    ticked = [s for s in states if s.get("status") in ("done", "skipped")]
    assert not ticked, (
        f"đánh dấu {ticked} dù người dùng chưa báo xong bước nào — "
        "quá giờ không phải là đã xong"
    )


# ── P3 — nhắc lại thì nhớ ──────────────────────────────────────────────

async def test_p3_a_later_mention_does_not_repeat_finished_steps(procedure_seeder):
    """Bài test trung tâm của P1.

    Sau khi người dùng báo xong bước 1, nhắc lại hoàn cảnh phải cho ra
    phần **còn lại**. Đọc lại cả ba bước là đúng hành vi mà người dùng mô
    tả là "hệ thống không nhớ gì".
    """
    procedure_id = await procedure_seeder()
    await run_turn("hôm nay tôi remote")

    # Tiền đề — "bước 1 đã xong" — được dựng **tất định**, không qua model.
    #
    # Bản đầu của test này để model tự đánh dấu bằng một lượt chat, và
    # thỉnh thoảng đỏ vì lượt đó không gọi tool. Nhưng "model có gọi
    # `mark_procedure_step` không" đã là bài P2; lặp lại nó ở đây chỉ làm
    # P3 thừa hưởng phương sai của P2 mà không kiểm thêm được gì. P3 hỏi
    # một câu khác: **khi tiến độ đã có, lần nhắc sau có tôn trọng nó
    # không.**
    await _mark_done(procedure_id, 1)

    # Hội thoại MỚI — không có tin nhắn cũ nào để dựa vào, tiến độ phải
    # đến từ run trong DB chứ không từ cửa sổ hội thoại.
    later = await run_turn("giờ tôi còn phải làm gì nữa")
    print(f"\n[P3] {later!r}")

    assert await judge(
        later.reply,
        "Câu trả lời liệt kê các việc CÒN LẠI (check-in trên web, sync với "
        "team) và KHÔNG yêu cầu người dùng làm lại 'Daily' — vì họ đã báo "
        "xong bước đó. Nhắc daily như một việc còn phải làm là FAIL.",
    )


# ── P4 — hoàn cảnh khác thì im ─────────────────────────────────────────

async def test_p4_an_unrelated_situation_does_not_open_the_procedure(procedure_seeder):
    """Ngưỡng khớp trigger chặt (0.70) chính vì đường này **ghi**.

    Khớp nhầm không chỉ làm nhiễu ngữ cảnh — nó mở một run và đọc cho
    người dùng danh sách việc của một hoàn cảnh khác.
    """
    await procedure_seeder()
    r = await run_turn("giá bitcoin hôm nay bao nhiêu")
    print(f"\n[P4] {r!r}")

    assert not r.called("mark_procedure_step")
    assert await judge(
        r.reply,
        "Câu trả lời KHÔNG nhắc tới quy trình làm việc từ xa (daily, "
        "check-in trên web, sync với team) — người dùng đang hỏi chuyện "
        "hoàn toàn khác.",
    )
