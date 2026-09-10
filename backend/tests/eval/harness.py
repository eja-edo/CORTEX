"""Chạy agent thật, gọi LLM thật, và thu lại đủ thứ để chấm điểm.

Vì sao không mock: bộ eval này tồn tại để trả lời "chất lượng giữa các
phiên có lệch nhau không". Câu hỏi đó *chỉ* có nghĩa với model thật —
một mock trả lời giống hệt nhau mọi lần, tức là nó luôn báo phương sai
bằng 0, đúng cái nó được dựng để đo.

Ba thứ được thu về sau mỗi lượt:

* `reply`      — chữ người dùng thật sự đọc
* `tool_calls` — đọc lại từ `agent_messages`, không phải từ giá trị trả
                 về của `handle()` (nó không trả). Đây là phần **cứng**
                 của phép chấm: "có tạo task không" là một sự thật trong
                 DB, không phải một suy đoán từ câu chữ.
* `latency_ms` — để một hồi quy về tốc độ không lẫn vào hồi quy chất lượng.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select, text

from app.ai.agents.agent_service import AgentService
from app.database_async import make_async_sessionmaker
from app.models import AgentMessage, User

# Tài khoản riêng của bộ eval — không dùng chung với
# `tests/integration/isolated_user.py`. Bộ eval xoá sạch tài khoản của nó
# giữa các kịch bản, và một test tích hợp chạy song song trên cùng id sẽ
# thấy dữ liệu của mình biến mất giữa chừng.
EVAL_USER_ID = UUID("00000000-0000-4000-a000-000000000e01")
EVAL_USER_EMAIL = "pytest-eval@cortex.invalid"


@dataclass
class TurnResult:
    """Kết quả một lượt nói."""

    reply: str
    tool_calls: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    latency_ms: float = 0.0

    def called(self, tool: str) -> bool:
        return tool in self.tool_calls

    def mentions(self, *keywords: str) -> bool:
        """Có nhắc tới **bất kỳ** từ khoá nào (không phân biệt hoa thường).

        Luôn nhận nhiều biến thể: model diễn đạt cùng một ý bằng nhiều
        cách, nên khớp một chuỗi duy nhất sẽ đo cách hành văn thay vì đo
        hành vi.
        """
        low = self.reply.lower()
        return any(k.lower() in low for k in keywords)

    def mentions_all(self, *keywords: str) -> bool:
        low = self.reply.lower()
        return all(k.lower() in low for k in keywords)

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log khi đỏ
        return (
            f"TurnResult(tools={self.tool_calls}, {self.latency_ms:.0f}ms, "
            f"reply={self.reply[:200]!r})"
        )


async def ensure_eval_user(db) -> UUID:
    await db.execute(
        text(
            "INSERT INTO users (id, email, full_name, hashed_password, is_active, created_at, updated_at) "
            "VALUES (:id, :email, 'pytest eval user', 'not-a-real-hash', true, NOW(), NOW()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": EVAL_USER_ID, "email": EVAL_USER_EMAIL},
    )
    await db.commit()
    return EVAL_USER_ID


async def reset_eval_user(db) -> None:
    """Về trạng thái trắng: mỗi kịch bản phải là một người dùng mới tinh.

    Không có bước này, bộ nhớ mà kịch bản trước dạy sẽ được recall trong
    kịch bản sau — chính xác kiểu nhiễu mà bộ eval đang đi đo.
    """
    # Cache dedupe của provider sống trong tiến trình và **không** biết
    # DB vừa bị xoá. Bỏ bước này thì lần seed thứ hai của cùng một nội dung
    # bị coi là trùng, `add_semantic_memory` trả True mà không ghi gì, và
    # test tiếp theo chạy trên một kho rỗng trong khi tưởng là đã seed.
    from app.services.pgvector_memory_provider import _reset_dedupe_cache

    _reset_dedupe_cache()

    uid = str(EVAL_USER_ID)
    await db.execute(
        text(
            "DELETE FROM agent_messages WHERE conversation_id IN "
            "(SELECT id FROM agent_conversations WHERE user_id = :u)"
        ),
        {"u": uid},
    )
    # `procedures` nằm trong danh sách vì `procedure_runs` treo dưới nó:
    # một run còn sót của test trước khiến test sau bắt đầu với tiến độ
    # không phải của nó, và triệu chứng là câu trả lời liệt kê thiếu bước.
    for table in (
        "agent_conversations", "semantic_memories", "tasks", "schedules",
        "notes", "procedures",
    ):
        col = "user_id"
        await db.execute(text(f"DELETE FROM {table} WHERE {col} = :u"), {"u": uid})
    await db.commit()


async def seed_memories(db, memories: list[tuple[str, str]]) -> None:
    """Nạp bộ nhớ dài hạn qua **đường ghi thật**, kèm embedding thật.

    Không INSERT thẳng: `add_semantic_memory` là nơi chuẩn hoá danh mục và
    sinh embedding, nên chèn tay sẽ vừa bỏ qua phần đang được test vừa tạo
    ra những hàng mà recall không bao giờ tìm thấy (embedding NULL).
    """
    from app.services.semantic_memory_provider import get_semantic_memory_provider

    provider = get_semantic_memory_provider(db)
    for category, content in memories:
        await provider.add_semantic_memory(
            user_id=str(EVAL_USER_ID),
            category=category,
            content=content,
            confidence=0.95,
            expected_lifetime="long",
        )
    await db.commit()


async def _tool_calls_for(db, conv_id: UUID, since_id: UUID | None = None) -> list[str]:
    stmt = (
        select(AgentMessage.tool_name)
        .where(
            AgentMessage.conversation_id == conv_id,
            AgentMessage.role == "tool",
            AgentMessage.tool_name.isnot(None),
        )
        .order_by(AgentMessage.created_at.asc())
    )
    return [r for r in (await db.execute(stmt)).scalars().all() if r]


async def run_turn(
    message: str,
    conversation_id: UUID | None = None,
    project_id: UUID | None = None,
) -> TurnResult:
    """Một lượt trò chuyện thật, từ đầu tới cuối.

    Session riêng cho mỗi lượt, cố ý: đường thật (một request HTTP) cũng
    dựng session mới mỗi lượt, và tái dùng một session xuyên nhiều lượt đã
    từng che giấu lỗi chỉ xuất hiện khi ngữ cảnh được đọc lại từ DB.
    """
    engine, session_maker = make_async_sessionmaker()
    try:
        async with session_maker() as db:
            user = (
                await db.execute(select(User).where(User.id == EVAL_USER_ID))
            ).scalar_one()

            t0 = time.perf_counter()
            result = await AgentService(user, db).handle(
                message=message,
                conversation_id=conversation_id,
                project_id=project_id,
            )
            latency = (time.perf_counter() - t0) * 1000

            conv_id = result.get("conversation_id")
            tools = await _tool_calls_for(db, UUID(conv_id)) if conv_id else []

            return TurnResult(
                reply=result.get("reply") or "",
                tool_calls=tools,
                conversation_id=conv_id,
                latency_ms=latency,
            )
    finally:
        await engine.dispose()
