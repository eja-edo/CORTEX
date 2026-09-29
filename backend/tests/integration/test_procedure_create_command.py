"""`procedure.create` — đường ghi trực tiếp cho quy trình lặp lại.

Thay cho đường cũ (chỉ tạo được gián tiếp, sau khi batch trích xuất bộ nhớ
phân loại đúng category `routine`, qua `procedure_extraction.py` — đã xoá).
Test ở đây đi qua **CommandRegistry**, không gọi thẳng `ProcedureService`,
cùng lý do đã ghi trong `test_procedure_quote_guard.py`: đó mới là đường
agent thật sự dùng.

Có chạm embedding thật — khớp-hay-tạo-mới dựa trên cosine similarity của
`trigger_text`, và một test giả lập embedding sẽ không kiểm được gì.
"""

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.ai.agents.tool_context import ToolContext
from app.commands.schemas import Command
from app.models import Procedure

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def create_setup():
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()

        yield uid

        await db.execute(text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
    await engine.dispose()


async def _run_create(uid, **args):
    """Chạy `procedure.create` qua registry, trên một session riêng như đường thật."""
    from app.commands.registry import get_command_registry
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        ctx = ToolContext(user_id=uid, async_db=db, conversation_id=uuid4())
        command = Command(
            command_name="procedure.create",
            args=args,
            requested_by=uid,
            source="AI",
        )
        try:
            result = await get_command_registry().execute(command, ctx)
        finally:
            ctx.close()
    await engine.dispose()
    return result


def _assert_applied(result):
    """Cùng lý do `test_procedure_quote_guard.py` đã nêu: `success=True` của
    `CommandResult` chỉ nói handler không ném lỗi, không nói thao tác đã
    thật sự xảy ra như định."""
    assert result.success, result.error
    assert result.data.get("success"), result.data


class TestCreate:
    async def test_creates_a_new_procedure_with_detail_and_timestamps_confirmation(self, create_setup):
        uid = create_setup
        result = await _run_create(
            uid,
            title="Quy trình khách mới",
            trigger_text="có khách hàng mới, khách mới liên hệ",
            steps=[
                {"title": "Tạo note giới thiệu", "detail": "tóm tắt nhu cầu khách, gắn note vào dự án tương ứng"},
                {"title": "Follow-up", "due_hint": "trong 3 ngày"},
            ],
        )
        _assert_applied(result)
        assert result.data["mode"] == "created"
        assert result.data["step_count"] == 2

        from app.database_async import make_async_sessionmaker

        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            procedure = await db.get(Procedure, UUID(result.data["procedure_id"]))
            assert procedure.steps[0]["detail"] == "tóm tắt nhu cầu khách, gắn note vào dự án tương ứng"
            assert procedure.steps[1]["due_hint"] == "trong 3 ngày"
            # Ghi mới cũng set last_confirmed_at ngay — không để trống chờ
            # lần mark_procedure_step đầu tiên.
            assert procedure.last_confirmed_at is not None
        await engine.dispose()

    async def test_same_trigger_updates_instead_of_duplicating(self, create_setup):
        uid = create_setup
        trigger = "khi tôi remote, làm việc từ xa"

        first = await _run_create(
            uid, title="Remote v1", trigger_text=trigger,
            steps=[{"title": "Daily"}],
        )
        _assert_applied(first)
        assert first.data["mode"] == "created"

        second = await _run_create(
            uid, title="Remote v2", trigger_text=trigger,
            steps=[{"title": "Daily"}, {"title": "Sync team", "due_hint": "4h chiều"}],
        )
        _assert_applied(second)
        assert second.data["mode"] == "updated"
        assert second.data["procedure_id"] == first.data["procedure_id"]

        from app.database_async import make_async_sessionmaker

        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            count = (
                await db.execute(
                    text("SELECT count(*) FROM procedures WHERE user_id = :u"),
                    {"u": str(uid)},
                )
            ).scalar()
            assert count == 1, "trigger trùng phải cập nhật, không tạo bản sao"

            procedure = await db.get(Procedure, UUID(second.data["procedure_id"]))
            assert procedure.title == "Remote v2"
            assert len(procedure.steps) == 2
        await engine.dispose()

    async def test_a_genuine_paraphrase_updates_not_duplicates(self, create_setup):
        """Khác test ở trên: KHÔNG dùng lại y nguyên chuỗi trigger_text.

        Cặp `"remote"` (đã dạy) vs `"hôm nào remote"` (dạy lại, câu khác
        hẳn) đã đo trực tiếp: cosine 0.7553, chung từ khoá "remote" — vượt
        `DEDUP_VECTOR_FLOOR` (0.70) và thoả AND. Đây đúng ca `save_procedure`
        sống đã gặp thật (T4, 2026-09-22): dạy lại bằng cách nói khác, chỉ
        còn chung đúng một từ, trước đây (chỉ vector, ngưỡng 0.90) sẽ luôn
        tạo bản sao.
        """
        uid = create_setup

        first = await _run_create(
            uid, title="Remote", trigger_text="remote, làm việc từ xa, wfh, làm việc ở nhà",
            steps=[{"title": "Daily", "due_hint": "trước 9h sáng"}],
        )
        _assert_applied(first)
        assert first.data["mode"] == "created"

        second = await _run_create(
            uid, title="Remote", trigger_text="hôm nào remote",
            steps=[{"title": "Daily"}, {"title": "Sync team", "due_hint": "4h chiều"}],
        )
        _assert_applied(second)
        assert second.data["mode"] == "updated", (
            "cách nói khác nhưng cùng hoàn cảnh phải cập nhật, không tạo bản sao"
        )
        assert second.data["procedure_id"] == first.data["procedure_id"]

    async def test_a_different_situation_that_merely_sounds_similar_does_not_merge(self, create_setup):
        """Đối chứng cho test trên: hai hoàn cảnh KHÁC NHAU thật, chỉ tình
        cờ gần nghĩa ("gấp gáp"), không được gộp dù vector một mình sẽ gộp
        nhầm. Đo trực tiếp: cosine("cuối tháng rồi", "deadline dự án sắp
        tới") = 0.7142 — vượt sàn vector 0.70 — nhưng không chung từ khoá
        nào ("cuối tháng" vs "deadline dự án"), nên AND đúng phải từ chối.
        """
        uid = create_setup

        first = await _run_create(
            uid, title="Chốt sổ cuối tháng", trigger_text="cuối tháng rồi, gần cuối tháng, tới kỳ chốt sổ",
            steps=[{"title": "Tổng hợp chi tiêu"}],
        )
        _assert_applied(first)
        assert first.data["mode"] == "created"

        second = await _run_create(
            uid, title="Deadline dự án", trigger_text="deadline dự án sắp tới",
            steps=[{"title": "Rà lại tiến độ"}],
        )
        _assert_applied(second)
        assert second.data["mode"] == "created", (
            "hai hoàn cảnh khác nhau thật bị gộp nhầm thành một"
        )
        assert second.data["procedure_id"] != first.data["procedure_id"]

    async def test_revert_of_a_new_procedure_soft_disables_it(self, create_setup):
        uid = create_setup
        result = await _run_create(
            uid, title="Tạm", trigger_text="hoàn cảnh chỉ để test revert",
            steps=[{"title": "Bước 1"}],
        )
        _assert_applied(result)
        assert result.action_id

        from app.commands.registry import get_command_registry
        from app.database_async import make_async_sessionmaker

        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            ctx = ToolContext(user_id=uid, async_db=db)
            try:
                revert_result = await get_command_registry().revert_command(result.action_id, ctx)
            finally:
                ctx.close()
            assert revert_result.success, revert_result.error

            procedure = await db.get(Procedure, UUID(result.data["procedure_id"]))
            assert procedure.is_active is False
        await engine.dispose()
