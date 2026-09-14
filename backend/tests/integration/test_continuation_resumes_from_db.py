"""Lượt "tiếp tục" phải thấy đúng những gì lượt trước đã làm.

Kịch bản: một lượt chạm `MAX_TOOL_TURNS` — hai tool đã chạy và có kết quả
thật trong DB, cộng một câu chốt tổng hợp mời "tiếp tục". Không gọi LLM
thật (đắt và không cần thiết ở đây): điều cần kiểm là tầng dựng lại lịch
sử từ DB, thứ mà lời mời "tiếp tục" hoàn toàn dựa vào.

Nếu tầng này dựng sai — bỏ mất tool đã gọi, hay tạo ra thứ tự role không
hợp lệ — thì lượt "tiếp tục" sẽ gửi cho model một lịch sử hỏng, và mọi lời
mời tiếp tục trong `CONTINUATION_INSTRUCTION` chỉ là hứa suông.
"""

from uuid import UUID

import pytest
import pytest_asyncio

from app.ai.agents.conversation_service import _build_history_contents
from app.ai.agents.tool_execution_service import _validate_contents_ordering
from app.ids import uuid7

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def cut_off_conversation():
    """Một hội thoại dừng đúng lúc chạm trần lượt gọi công cụ."""
    from app.database_async import make_async_sessionmaker
    from app.ai.agents.conversation_store import ConversationStore
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        store = ConversationStore(db)
        conv = await store.get_or_create_conversation(user_id=uid, title="test")

        await store.save_message(
            conversation_id=conv.id, role="user",
            content="Tạo cho tôi 20 task theo danh sách này",
        )

        turn_id = uuid7()
        await store.save_message(
            conversation_id=conv.id, role="tool", tool_name="create_task",
            tool_input={"title": "Việc 1"}, tool_output={"success": True, "id": "t1"},
            tool_call_id="call_1", turn_id=turn_id,
        )
        await store.save_message(
            conversation_id=conv.id, role="tool", tool_name="create_task",
            tool_input={"title": "Việc 2"}, tool_output={"success": True, "id": "t2"},
            tool_call_id="call_2", turn_id=turn_id,
        )

        await store.save_message(
            conversation_id=conv.id, role="assistant",
            content=(
                "Mình đã tạo xong 2/20 việc: Việc 1, Việc 2. Còn 18 việc "
                'nữa. Bạn gõ "tiếp tục" để mình làm nốt nhé.'
            ),
        )
        await db.commit()
        conv_id = conv.id

    yield conv_id

    async with session_maker() as db:
        from sqlalchemy import text

        await db.execute(text("DELETE FROM agent_conversations WHERE id = :c"), {"c": str(conv_id)})
        await db.commit()
    await engine.dispose()


async def _reload(conv_id: UUID):
    from app.database_async import make_async_sessionmaker
    from sqlalchemy import select
    from app.models import AgentMessage

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        rows = (
            await db.execute(
                select(AgentMessage)
                .where(AgentMessage.conversation_id == conv_id)
                .order_by(AgentMessage.created_at)
            )
        ).scalars().all()
    await engine.dispose()
    return list(rows)


class TestReconstructedHistory:
    async def test_both_tool_calls_survive_the_reload(self, cut_off_conversation):
        rows = await _reload(cut_off_conversation)
        messages = _build_history_contents(rows)

        tool_names = [
            tc.name
            for m in messages
            if m.tool_calls
            for tc in m.tool_calls
        ]
        assert tool_names == ["create_task", "create_task"]

    async def test_tool_results_are_visible_not_just_the_calls(self, cut_off_conversation):
        """Model phải thấy KẾT QUẢ, không chỉ việc đã gọi — nếu không, nó
        không biết task nào đã tạo thành công để tránh tạo trùng."""
        rows = await _reload(cut_off_conversation)
        messages = _build_history_contents(rows)

        tool_results = [m for m in messages if m.tool_result is not None]
        contents = [tr.tool_result.content for tr in tool_results]
        assert any("t1" in str(c) for c in contents)
        assert any("t2" in str(c) for c in contents)

    async def test_checkpoint_text_is_the_last_message(self, cut_off_conversation):
        """Câu chốt mời tiếp tục phải là thứ cuối cùng model đọc được."""
        rows = await _reload(cut_off_conversation)
        messages = _build_history_contents(rows)

        assert messages[-1].role == "assistant"
        assert "tiếp tục" in messages[-1].content

    async def test_reconstructed_history_is_valid_for_the_next_call(
        self, cut_off_conversation
    ):
        """Đây là điều kiện thật sự cần: lịch sử dựng lại phải nạp được vào
        lượt kế tiếp mà không vi phạm ràng buộc thứ tự role."""
        from app.ai.agents.provider_types import Message

        rows = await _reload(cut_off_conversation)
        messages = _build_history_contents(rows)
        messages.append(Message(role="user", content="tiếp tục"))

        is_valid, reason = _validate_contents_ordering(messages)
        assert is_valid, reason
