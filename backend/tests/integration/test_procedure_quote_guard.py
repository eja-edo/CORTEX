"""`procedure.mark_step` chỉ ghi khi người dùng thật sự đã nói.

Đây là phép chặn cho một hành vi đo được: model diễn giải "quá giờ" thành
"đã xong" rồi đánh dấu hộ người dùng. Xem `tests/unit/
test_procedure_quote_guard.py` cho số đo, và
`app.commands.handlers.procedure_commands._quote_is_real` cho lý lẽ.

Test ở đây đi qua **CommandRegistry**, không gọi thẳng service: đó mới là
đường mà agent thật sự dùng, và phép kiểm sống ở tầng đó.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from uuid import uuid4

from app.ai.agents.tool_context import ToolContext
from app.commands.schemas import Command
from app.services.procedures import ProcedureService

pytestmark = pytest.mark.asyncio

STEPS = [
    {"title": "Daily", "due_hint": "trước 9h sáng"},
    {"title": "Check-in trên web"},
]


@pytest_asyncio.fixture
async def guard_setup():
    """Quy trình + run đang mở + một hội thoại có lời người dùng thật."""
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)})
        await db.execute(
            text(
                "DELETE FROM agent_messages WHERE conversation_id IN "
                "(SELECT id FROM agent_conversations WHERE user_id = :u)"
            ),
            {"u": str(uid)},
        )
        await db.execute(text("DELETE FROM agent_conversations WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()

        procedure = await ProcedureService(db).create(
            user_id=uid, title="Quy trình remote",
            trigger_text="remote, wfh", steps=STEPS,
        )
        run = await ProcedureService(db).get_or_open_run(procedure)

        conv_id = (
            await db.execute(
                text(
                    "INSERT INTO agent_conversations (user_id, title) "
                    "VALUES (:u, 'test') RETURNING id"
                ),
                {"u": str(uid)},
            )
        ).scalar()
        for content in ("hôm nay tôi remote", "daily xong rồi nhé"):
            await db.execute(
                text(
                    "INSERT INTO agent_messages (id, conversation_id, role, content) "
                    "VALUES (uuid_generate_v7(), :c, 'user', :m)"
                ),
                {"c": conv_id, "m": content},
            )
        await db.commit()

        yield uid, procedure.id, run.id, conv_id

        await db.execute(text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)})
        await db.execute(
            text(
                "DELETE FROM agent_messages WHERE conversation_id IN "
                "(SELECT id FROM agent_conversations WHERE user_id = :u)"
            ),
            {"u": str(uid)},
        )
        await db.execute(text("DELETE FROM agent_conversations WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
    await engine.dispose()


async def _run_command(uid, conv_id, current_message=None, **args):
    """Chạy command qua registry, trên một session riêng như đường thật.

    `current_message` mô phỏng đúng thứ agent truyền xuống: lượt nói của
    lượt hiện tại, thứ **chưa** có trong DB lúc tool chạy (save_message chỉ
    flush, không commit).
    """
    from app.commands.registry import get_command_registry
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        ctx = ToolContext(
            user_id=uid, async_db=db, conversation_id=conv_id,
            current_message=current_message,
        )
        command = Command(
            command_name="procedure.mark_step",
            args=args,
            requested_by=uid,
            conversation_id=conv_id,
            source="AI",
        )
        try:
            result = await get_command_registry().execute(command, ctx)
        finally:
            ctx.close()
    await engine.dispose()
    return result


def _assert_applied(result):
    """Thao tác thật sự đã xảy ra — không chỉ là "command chạy xong".

    `CommandResult.success` chỉ nói handler không ném lỗi. Handler trả
    `{"success": False, "error": "quote_not_found"}` vẫn cho
    `result.success is True`, nên một test chỉ assert nó sẽ xanh ngay cả
    khi phép kiểm đã chặn — tức là nó canh đúng thứ nó định canh thì
    không phát hiện được gì.
    """
    assert result.success, result.error
    assert (result.data or {}).get("success") is True, (result.data or {}).get("error")


async def _done_orders(procedure_id):
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        run = await ProcedureService(db).get_active_run(procedure_id)
        orders = [
            s["order"] for s in (run.step_states or []) if s.get("status") == "done"
        ] if run else []
    await engine.dispose()
    return orders


class TestQuoteMustBeReal:
    async def test_a_real_quote_is_accepted(self, guard_setup):
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="daily xong rồi nhé",
        )
        _assert_applied(result)
        assert await _done_orders(pid) == [1]

    async def test_a_fabricated_quote_is_rejected(self, guard_setup):
        """Kiểu hỏng chính: model tự nghĩ ra lý do rồi ghi thay người dùng."""
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="đã quá 9h sáng nên coi như xong",
        )
        assert result.data.get("error") == "quote_not_found"
        assert await _done_orders(pid) == [], "đã ghi dù trích dẫn là bịa"

    async def test_a_paraphrase_is_rejected(self, guard_setup):
        """Diễn giải lại cũng không được — nguyên văn hoặc không gì cả.

        Nới ra để chấp nhận paraphrase sẽ mở lại đúng khoảng trống mà phép
        kiểm này đóng: model luôn diễn giải được thành một câu nghe hợp lý.
        """
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="người dùng đã hoàn thành daily",
        )
        assert result.data.get("error") == "quote_not_found"

    async def test_partial_quote_of_a_real_message_is_accepted(self, guard_setup):
        """Trích một phần câu thật vẫn hợp lệ — model không phải copy cả câu."""
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="daily xong",
        )
        _assert_applied(result)
        assert await _done_orders(pid) == [1]

    async def test_case_and_spacing_differences_are_forgiven(self, guard_setup):
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="  DAILY   XONG rồi  ",
        )
        _assert_applied(result)
        assert await _done_orders(pid) == [1]

    async def test_an_assistant_sentence_does_not_count(self, guard_setup):
        """Chỉ lời NGƯỜI DÙNG mới là bằng chứng.

        Không có ràng buộc này, agent có thể tự nói "vậy là xong daily nhé"
        ở lượt trước rồi trích dẫn chính mình làm căn cứ.
        """
        from app.database_async import make_async_sessionmaker

        uid, pid, _, conv_id = guard_setup
        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            await db.execute(
                text(
                    "INSERT INTO agent_messages (id, conversation_id, role, content) "
                    "VALUES (uuid_generate_v7(), :c, 'assistant', :m)"
                ),
                {"c": conv_id, "m": "vậy là xong bước sync với team nhé"},
            )
            await db.commit()
        await engine.dispose()

        result = await _run_command(
            uid, conv_id,
            procedure_id=str(pid), step_order=2, status="done",
            user_said="vậy là xong bước sync với team nhé",
        )
        assert result.data.get("error") == "quote_not_found"


class TestCurrentTurnIsEvidenceToo:
    """Câu người dùng **vừa** gõ cũng là bằng chứng — và là ca thường gặp nhất.

    Bản đầu của phép kiểm chỉ tra `agent_messages`, và nó **hỏng đúng ở ca
    phổ biến nhất**: `ConversationStore.save_message` chỉ `flush()`, không
    commit, nên tin nhắn của lượt hiện tại còn nằm trong transaction chưa
    xong của session agent, còn tool thì chạy trên session riêng. Đo được
    trên đường thật: người dùng nói "daily xong rồi nhé" → agent trả lời
    "mình đã ghi nhận" → `done = []` trong DB.

    Nhóm test này dựng dữ liệu **giống đường thật** (câu hiện tại chỉ có
    trong `ToolContext`, không có trong DB) — thứ mà `TestQuoteMustBeReal`
    không làm, và vì thế nó xanh trong khi tính năng đang hỏng.
    """

    async def test_quote_from_the_current_turn_is_accepted(self, guard_setup):
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            current_message="check-in xong rồi nhé",
            procedure_id=str(pid), step_order=2, status="done",
            user_said="check-in xong rồi",
        )
        _assert_applied(result)
        assert await _done_orders(pid) == [2]

    async def test_a_fabricated_quote_is_still_rejected(self, guard_setup):
        """Có `current_message` không có nghĩa là buông phép kiểm."""
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            current_message="hôm nay tôi remote",
            procedure_id=str(pid), step_order=1, status="done",
            user_said="đã quá 9h nên coi như xong",
        )
        assert result.data.get("error") == "quote_not_found"
        assert await _done_orders(pid) == []

    async def test_works_without_any_conversation_history(self, guard_setup):
        """Lượt đầu tiên của một hội thoại chưa có tin nhắn nào đã commit."""
        uid, pid, _, _ = guard_setup
        result = await _run_command(
            uid, None,
            current_message="daily xong rồi",
            procedure_id=str(pid), step_order=1, status="done",
            user_said="daily xong rồi",
        )
        _assert_applied(result)
        assert await _done_orders(pid) == [1]

    async def test_no_message_and_no_conversation_is_refused(self, guard_setup):
        """Không còn gì để đối chiếu thì từ chối, không phải bỏ qua."""
        uid, pid, _, _ = guard_setup
        result = await _run_command(
            uid, None,
            procedure_id=str(pid), step_order=1, status="done",
            user_said="daily xong rồi",
        )
        assert result.data.get("error") == "no_conversation_context"


class TestGuardScope:
    async def test_pending_needs_no_quote(self, guard_setup):
        """Bỏ đánh dấu là hoàn tác, không phải khẳng định người dùng đã làm gì."""
        uid, pid, _, conv_id = guard_setup
        ok = await _run_command(
            uid, conv_id, procedure_id=str(pid), step_order=1,
            status="done", user_said="daily xong rồi nhé",
        )
        _assert_applied(ok)

        undo = await _run_command(
            uid, conv_id, procedure_id=str(pid), step_order=1,
            status="pending", user_said="",
        )
        _assert_applied(undo)
        assert await _done_orders(pid) == []

    async def test_skipped_still_needs_a_quote(self, guard_setup):
        """`skipped` cũng là một khẳng định về ý định của người dùng.

        "Hôm nay khỏi sync" là quyết định của họ, không phải suy đoán của
        agent — nên nó cần bằng chứng như `done`.
        """
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id, procedure_id=str(pid), step_order=2,
            status="skipped", user_said="thôi hôm nay khỏi sync",
        )
        assert result.data.get("error") == "quote_not_found"

    async def test_skipped_needs_a_skip_word_not_just_any_quote(self, guard_setup):
        """Lỗ hổng đã biết của phép kiểm trích dẫn, chặn riêng cho `skipped`.

        Phép kiểm chỉ xác minh câu trích *có thật*, không xác minh nó *nói
        về điều đang được ghi*. Đo được: agent đánh dấu bước "sync với team"
        là bỏ qua trong khi người dùng chưa hề nói tới việc bỏ bước nào — nó
        chỉ cần trích một câu thật bất kỳ là qua.
        """
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            current_message="hôm nay tôi remote",
            procedure_id=str(pid), step_order=2, status="skipped",
            user_said="hôm nay tôi remote",
        )
        assert result.data.get("error") == "no_skip_intent"
        assert await _done_orders(pid) == []

    async def test_skipped_passes_with_a_real_skip(self, guard_setup):
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            current_message="thôi khỏi check-in hôm nay",
            procedure_id=str(pid), step_order=2, status="skipped",
            user_said="thôi khỏi check-in",
        )
        _assert_applied(result)

    async def test_done_does_not_need_a_skip_word(self, guard_setup):
        """`done` cố ý KHÔNG chịu phép kiểm này.

        Người dùng xác nhận đã làm xong bằng đủ kiểu ngắn gọn sau khi agent
        hỏi — "ok", "ừ", "rồi". Đòi từ khoá ở đó sẽ chặn oan ca hợp lệ phổ
        biến nhất.
        """
        uid, pid, _, conv_id = guard_setup
        result = await _run_command(
            uid, conv_id,
            current_message="daily xong rồi",
            procedure_id=str(pid), step_order=1, status="done",
            user_said="daily xong rồi",
        )
        _assert_applied(result)

    async def test_another_users_procedure_is_not_found(self, guard_setup):
        """Không phải chủ sở hữu thì là 404, không phải 403."""
        _, pid, _, conv_id = guard_setup
        result = await _run_command(
            uuid4(), conv_id, procedure_id=str(pid), step_order=1,
            status="done", user_said="daily xong rồi nhé",
        )
        assert result.data.get("error") == "procedure_not_found"
