"""Vòng học hai chiều: hành vi của người dùng → mức → hành vi của Cortex.

Trước khi có nửa này, `feedback_loop` chỉ ăn tín hiệu từ nút dismiss trên
một notification. Người dùng nói "thôi không cần" mười lần trong chat thì
không gì được ghi lại, nên mức can thiệp không bao giờ hạ — trong khi chat
mới là bề mặt họ ở nhiều nhất.

Tín hiệu được dùng là **tất định**: `task.reject`, tức người dùng bấm/nói
"không" với một việc bộ trích xuất đoán ra. Cố ý không suy ra "từ chối" từ
câu chữ và không để model tự khai bằng một tool — đợt `mark_procedure_step`
đã đo được rằng model sẵn sàng khai một điều nó suy diễn ra, và một vòng học
ăn dữ liệu do model phán đoán sẽ học chính những phán đoán sai đó.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from uuid import uuid4

from app.config import settings
from app.models import AttentionLevel, AttentionItemType
from app.services.attention_reason_catalog import base_level_for
from app.services.intervention import conversational_level, record_chat_dismissal

pytestmark = pytest.mark.asyncio

REASON = "task.suggestion"


@pytest_asyncio.fixture
async def loop_user():
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(text("DELETE FROM attention_log WHERE user_id = :u"), {"u": str(uid)})
        await db.execute(text("DELETE FROM user_preferences WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
        yield db, uid
        await db.rollback()
        await db.execute(text("DELETE FROM attention_log WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
    await engine.dispose()


class TestTheWriteHalf:
    async def test_a_dismissal_is_recorded(self, loop_user):
        db, uid = loop_user
        ok = await record_chat_dismissal(
            db, uid, reason_key=REASON,
            item_type=AttentionItemType.TASK, item_id=uuid4(),
        )
        assert ok

        count = (
            await db.execute(
                text(
                    "SELECT count(*) FROM attention_log WHERE user_id = :u "
                    "AND reason_key = :r AND response = 'dismissed'"
                ),
                {"u": str(uid), "r": REASON},
            )
        ).scalar()
        assert count == 1

    async def test_the_row_records_both_halves(self, loop_user):
        """Một hàng mang cả "đã đề xuất" lẫn "bị từ chối".

        Ở chat không ai ghi phần đầu — agent nói đề xuất trong câu trả lời,
        không qua `record_surface`. Tách thành hai hàng sẽ để lại một hàng
        `no_response` vĩnh viễn không ai đóng.
        """
        db, uid = loop_user
        await record_chat_dismissal(
            db, uid, reason_key=REASON,
            item_type=AttentionItemType.TASK, item_id=uuid4(),
        )
        row = (
            await db.execute(
                text(
                    "SELECT response::text, responded_at, level::text, channel::text "
                    "FROM attention_log WHERE user_id = :u"
                ),
                {"u": str(uid)},
            )
        ).one()
        response, responded_at, level, channel = row
        assert response == "dismissed"
        assert responded_at is not None, "phản hồi không có thời điểm"
        assert level  # mức lúc đề xuất
        assert channel == "in_app"

    async def test_failure_is_non_fatal(self, loop_user, monkeypatch):
        """Ghi nhận bên lề không được làm thao tác chính thất bại.

        Người dùng vừa từ chối một việc thành công; mất một điểm dữ liệu của
        vòng học còn hơn làm thao tác đó đỏ.
        """
        db, uid = loop_user

        async def boom(*args, **kwargs):
            raise RuntimeError("sập")

        monkeypatch.setattr("app.services.intervention.conversational_level", boom)
        ok = await record_chat_dismissal(
            db, uid, reason_key=REASON,
            item_type=AttentionItemType.TASK, item_id=uuid4(),
        )
        assert ok is False


class TestTheLoopActuallyCloses:
    """Từ chối nhiều lần → mức hạ → Cortex thôi đề xuất.

    Đây là bài test trung tâm: hai nửa rời nhau thì mỗi nửa đều vô nghĩa.
    Ghi mà không ai đọc là thống kê; đọc mà không ai ghi là một hằng số.
    """

    async def test_dismissals_from_chat_lower_the_level(self, loop_user):
        db, uid = loop_user
        assert await conversational_level(db, uid, REASON) == base_level_for(REASON)

        for _ in range(settings.FEEDBACK_LOOP_DISMISS_THRESHOLD):
            await record_chat_dismissal(
                db, uid, reason_key=REASON,
                item_type=AttentionItemType.TASK, item_id=uuid4(),
            )
        await db.commit()

        ladder = [
            AttentionLevel.SILENT, AttentionLevel.INFORM, AttentionLevel.RECOMMEND,
            AttentionLevel.ASK, AttentionLevel.ACT,
        ]
        after = await conversational_level(db, uid, REASON)
        assert ladder.index(after) == ladder.index(base_level_for(REASON)) - 1

    async def test_enough_dismissals_silence_the_feature(self, loop_user):
        """Xuống tới SILENT thì bộ trích xuất thôi tạo candidate."""
        from app.services.task_extraction import TaskCandidateService

        db, uid = loop_user
        # ASK → SILENT là ba bậc.
        for _ in range(settings.FEEDBACK_LOOP_DISMISS_THRESHOLD * 3):
            await record_chat_dismissal(
                db, uid, reason_key=REASON,
                item_type=AttentionItemType.TASK, item_id=uuid4(),
            )
        await db.commit()
        assert await conversational_level(db, uid, REASON) == AttentionLevel.SILENT

        result = await TaskCandidateService(db).store_candidates(
            raw_candidates=[{
                "expected_action": "gửi proposal",
                "counterparty": "John",
                "source_quote": "thứ 6 tôi gửi proposal cho John",
            }],
            user_id=uid,
        )
        assert result["created_count"] == 0
        assert result["skipped_silenced"] == 1

    async def test_a_fresh_user_still_gets_suggestions(self, loop_user):
        """Phép chặn chỉ áp cho người đã tỏ ra không muốn.

        Nếu nó áp cho mọi người thì đây không phải vòng học, chỉ là tắt
        tính năng.
        """
        from app.services.task_extraction import TaskCandidateService

        db, uid = loop_user
        result = await TaskCandidateService(db).store_candidates(
            raw_candidates=[{
                "expected_action": "gửi proposal",
                "counterparty": "John",
                "source_quote": "thứ 6 tôi gửi proposal cho John",
            }],
            user_id=uid,
        )
        assert result["skipped_silenced"] == 0
        await db.rollback()

    async def test_both_return_branches_have_the_same_keys(self, loop_user):
        """Nhánh sớm trả khoá khác nhánh thường là kiểu hỏng im lặng.

        `memory_extraction_service` đọc kết quả theo khoá và log nó; một
        `KeyError` ở đó sẽ xuất hiện như "task extraction failed" chứ không
        như "người dùng đã tắt tính năng này".
        """
        import inspect
        import re

        from app.services.task_extraction import TaskCandidateService

        src = inspect.getsource(TaskCandidateService.store_candidates)
        blocks = re.findall(r"return \{(.*?)\n\s*\}", src, re.S)
        assert len(blocks) >= 2, "không tìm thấy cả hai nhánh trả về"
        keysets = {tuple(sorted(set(re.findall(r'"(\w+)":', b)))) for b in blocks}
        assert len(keysets) == 1, f"hai nhánh trả khoá khác nhau: {keysets}"


class TestOnlyDeterministicSignals:
    """Vòng học chỉ được ăn tín hiệu tất định.

    Không có tool nào cho model tự khai "người dùng vừa từ chối", và đó là
    quyết định thiết kế, không phải việc chưa làm: model sẵn sàng khai một
    điều nó suy diễn ra (đã đo ở `mark_procedure_step` — nó đọc "quá giờ"
    thành "đã xong" rồi ghi vào DB). Một vòng học ăn phán đoán của model sẽ
    học chính những phán đoán sai đó.
    """

    def test_no_tool_lets_the_model_report_a_dismissal(self):
        from app.ai.agents.tool_registry import get_tool_registry

        names = {t.name for t in get_tool_registry().get_provider_tools()}
        for suspicious in ("record_dismissal", "record_suggestion_response",
                           "report_rejection", "dismiss_suggestion"):
            assert suspicious not in names

    def test_reject_handler_is_the_write_site(self):
        import inspect

        from app.commands.handlers import task_commands

        src = inspect.getsource(task_commands.task_reject_handler)
        assert "record_chat_dismissal" in src

    def test_only_ai_guessed_tasks_count(self):
        """Người dùng tự gõ một việc rồi tự xoá không nói gì về Cortex."""
        import inspect

        from app.commands.handlers import task_commands

        src = inspect.getsource(task_commands.task_reject_handler)
        assert "source_conversation_id is not None" in src
