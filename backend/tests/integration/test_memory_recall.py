"""Recall bộ nhớ dài hạn — phần tất định, không cần LLM.

Bộ eval sống (`tests/eval/`) kiểm việc model *dùng* khối bộ nhớ ra sao.
Tệp này kiểm phần dưới nó: bộ nhớ có tới được ngữ cảnh không, có bị chặn
đúng chỗ không, và hỏng thì có làm chết lượt chat không. Những câu hỏi đó
không cần model để trả lời, nên chúng không nằm sau marker `live_llm`.

Có chạm embedding thật (dịch vụ nội bộ, không phải API tính tiền theo
token) vì recall không có nghĩa gì nếu thiếu nó: một hàng `embedding
IS NULL` không bao giờ được tìm thấy, và đó đúng là kiểu hỏng mà chèn
thẳng SQL trong test sẽ giấu đi.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.context.context_service import ContextService
from app.context.schemas import RecalledMemory, UnifiedContext

pytestmark = pytest.mark.asyncio

REMOTE_ROUTINE = (
    "Khi tôi remote thì phải daily trước 9h sáng, check-in trên web, "
    "và sync với team lúc 4h chiều."
)


@pytest_asyncio.fixture
async def memory_user():
    """Tài khoản cô lập, kho bộ nhớ trắng, đã nạp sẵn một quy trình."""
    from app.database_async import make_async_sessionmaker
    from app.services.pgvector_memory_provider import _reset_dedupe_cache
    from app.services.semantic_memory_provider import get_semantic_memory_provider
    from tests.integration.isolated_user import ensure_isolated_user

    # Provider nhớ trong tiến trình những nội dung nó đã ghi, để khỏi ghi
    # trùng. Cache đó không biết fixture này vừa xoá bảng — nên nếu không
    # dọn, test thứ hai dùng fixture này seed vào hư không và chạy trên kho
    # rỗng. Triệu chứng: xanh khi chạy một mình, đỏ khi chạy cả bộ.
    _reset_dedupe_cache()

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(
            text("DELETE FROM semantic_memories WHERE user_id = :u"), {"u": str(uid)}
        )
        await db.commit()

        await get_semantic_memory_provider(db).add_semantic_memory(
            user_id=str(uid),
            category="routine",
            content=REMOTE_ROUTINE,
            confidence=0.95,
            expected_lifetime="long",
        )
        await db.commit()
        yield uid

        await db.execute(
            text("DELETE FROM semantic_memories WHERE user_id = :u"), {"u": str(uid)}
        )
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def async_db():
    from app.database_async import make_async_sessionmaker

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        yield db
    await engine.dispose()


class TestRecallReachesContext:
    async def test_matching_message_surfaces_the_memory(self, memory_user, async_db):
        ctx = await ContextService(async_db).build_context(
            user_id=memory_user, message="hôm nay tôi remote"
        )
        assert len(ctx.recalled_memories) == 1
        assert ctx.recalled_memories[0].category == "routine"
        assert "daily" in ctx.recalled_memories[0].content

    async def test_unrelated_message_surfaces_nothing(self, memory_user, async_db):
        """Sàn liên quan phải cắt được phần rõ ràng lạc đề.

        Không có nó, tìm kiếm vector luôn trả về hàng *gần nhất* — với kho
        một hàng thì đó luôn là hàng duy nhất, bất kể người dùng hỏi gì.
        """
        ctx = await ContextService(async_db).build_context(
            user_id=memory_user, message="thời tiết hôm nay thế nào"
        )
        assert ctx.recalled_memories == []

    async def test_memory_reaches_the_system_prompt_string(self, memory_user, async_db):
        ctx = await ContextService(async_db).build_context(
            user_id=memory_user, message="hôm nay tôi remote"
        )
        rendered = ctx.to_llm_string()
        assert "long-term memory" in rendered.lower()
        assert "daily" in rendered

    async def test_empty_message_skips_recall_entirely(self, memory_user, async_db):
        """Không có gì để tra thì đừng tra — mỗi lần recall là một lần embed."""
        ctx = await ContextService(async_db).build_context(
            user_id=memory_user, message=""
        )
        assert ctx.recalled_memories == []

    async def test_recall_is_scoped_to_the_owner(self, memory_user, async_db):
        """Bộ nhớ khoá theo người. Một user khác không được thấy gì."""
        from uuid import uuid4

        ctx = await ContextService(async_db).build_context(
            user_id=uuid4(), message="hôm nay tôi remote"
        )
        assert ctx.recalled_memories == []


class TestRecallNeverBreaksTheTurn:
    async def test_provider_failure_is_non_fatal(self, memory_user, async_db, monkeypatch):
        """Bộ nhớ là phần làm giàu ngữ cảnh, không phải điều kiện để trả lời.

        Nếu một lỗi ở đây ném ra ngoài, nó sẽ giết cả lượt chat — đổi một
        câu trả lời hơi kém giàu ngữ cảnh thành không có câu trả lời nào.
        """

        def boom(*args, **kwargs):
            raise RuntimeError("kho bộ nhớ sập")

        monkeypatch.setattr(
            "app.services.semantic_memory_provider.get_semantic_memory_provider", boom
        )

        ctx = await ContextService(async_db).build_context(
            user_id=memory_user, message="hôm nay tôi remote"
        )
        assert ctx.recalled_memories == []
        # phần còn lại của ngữ cảnh vẫn phải dựng được
        assert isinstance(ctx, UnifiedContext)


class TestRenderedGuidance:
    """Khối chỉ dẫn đi kèm bộ nhớ, không phải trang trí.

    Nó xuất hiện ở **mọi** lượt, kể cả khi bộ nhớ được kéo lên chỉ vì tình
    cờ gần nghĩa (điểm ~0.58 không tách được đúng khỏi sai — xem
    `MIN_RELEVANCE_SCORE`). Ba dòng này là thứ duy nhất còn lại ngăn model
    hành động theo một quy trình người dùng không hề nhắc tới, nên chúng
    được canh như code.
    """

    def _rendered(self) -> str:
        return UnifiedContext(
            recalled_memories=[
                RecalledMemory(content=REMOTE_ROUTINE, category="routine", score=0.61)
            ]
        ).to_llm_string()

    def test_says_the_user_did_not_just_say_these(self):
        assert "did NOT just say" in self._rendered()

    def test_tells_the_model_to_check_the_trigger(self):
        assert "Check the trigger" in self._rendered()

    def test_forbids_acting_on_memory_alone(self):
        rendered = self._rendered()
        assert "Never create, modify or delete anything from this section alone" in rendered

    def test_no_memories_renders_no_block(self):
        assert UnifiedContext().to_llm_string() == ""
