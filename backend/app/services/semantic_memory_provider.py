"""
SemanticMemoryProvider interface.

Abstract base class for semantic memory backends.
Current implementations:
- ZepMemoryService (via zep_memory.py)
- PgVectorMemoryProvider (pgvector fallback)

FallbackSemanticMemoryProvider wraps ZepMemoryProvider as primary
and PgVectorMemoryProvider as fallback when Zep is unavailable.
"""

import logging
from abc import ABC, abstractmethod
from typing import NotRequired, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# Sàn chặn rác, **không phải** bộ lọc liên quan — và là ngưỡng chung cho
# *mọi* đường đọc bộ nhớ (tool `extract_memory` và recall tự động của
# `ContextService`). Hai ngưỡng khác nhau cho cùng một kho sẽ làm cùng một
# câu hỏi cho hai câu trả lời tuỳ nó đi đường nào.
#
# Con số này nằm trên thang **cosine similarity**. Trước 2026-09-10 nó nằm
# trên một thang khác mà không ai biết: truy vấn dùng toán tử khoảng cách
# L2 kèm công thức `1 - d/2` của cosine, nên `0.55` khi đó thực chất là
# cosine ≈ 0.595 — chặt hơn nhiều so với ý định. Đo được hậu quả: ràng buộc
# "không bao giờ họp sau 18h" đạt 0.5611 với câu "đặt lịch họp lúc 19h tối
# mai", tức là **bị loại**, và agent đặt lịch 19h mà không hề biết có xung
# đột.
#
# Đo lại trên thang đúng (2026-09-10, `gemini-embedding-2-preview`, 4 bộ
# nhớ: routine remote / preference gym / constraint không-họp-sau-18h /
# goal IELTS):
#
#     câu hỏi                              bộ nhớ đúng   nhiễu cao nhất
#     làm việc từ xa                       0.7316 ✓      0.5350
#     hôm nay tôi remote                   0.6952 ✓      0.5139
#     tôi học tiếng anh thế nào rồi        0.6675 ✓      0.6007
#     mai tôi đi gym                       0.6452        0.6528 ✗ remote
#     tối mai họp lúc 7 giờ tối được không 0.6297        0.6792 ✗ remote
#     đặt lịch họp với khách lúc 19h       0.5611        0.6608 ✗ remote
#     deadline dự án sắp tới rồi           (không có)    0.7130
#     thời tiết hôm nay thế nào            (không có)    0.5320
#     giá bitcoin bao nhiêu                (không có)    0.5389
#
# Hai điều rút ra, và cả hai đều định hình thiết kế quanh con số này:
#
# **Không ngưỡng nào tách được đúng khỏi sai.** Dải đúng [0.5611, 0.7316]
# nằm gọn trong dải nhiễu [0.3878, 0.7130]. Bộ nhớ routine remote xếp hạng
# nhất ở 8/9 truy vấn — kể cả "giá bitcoin bao nhiêu" — vì nó là văn bản
# dài nhất và giàu từ nhất, không vì nó liên quan. Đây là hành vi đã biết
# của embedding trên đoạn dài, không phải lỗi cấu hình.
#
# **Nên ngưỡng chỉ làm một việc khiêm tốn: cắt phần rõ ràng lạc đề** (~0.53
# trở xuống — "thời tiết", "bitcoin"). Việc phán đoán "quy trình này có
# thật sự nói về hoàn cảnh người dùng vừa nêu không" giao cho model: nó
# *đọc* được vế "khi tôi remote" và thấy ngay "deadline dự án" không khớp,
# thứ một phép so sánh số không làm được. Khối chỉ dẫn trong
# `UnifiedContext._render_memories()` là nơi ra lệnh đó, và
# `tests/eval/test_memory_recall_live.py` cấp 3 là nơi kiểm nó.
#
# Sửa gốc cho thứ hạng nằm ở tầng dữ liệu, không ở con số này: tách vế
# trigger ("khi tôi remote") ra khỏi phần các bước rồi so khớp riêng nó,
# thay vì embed cả đoạn dài làm một.
MIN_RELEVANCE_SCORE = 0.55


class SemanticMemoryUnavailable(Exception):
    """Raised when the semantic memory backend (e.g. Zep Cloud) is unreachable or errors."""



class SemanticMemoryResult(TypedDict):
    id: str
    content: str
    category: str
    confidence: NotRequired[float]
    score: float
    created_at: NotRequired[str]


class SemanticMemoryProvider(ABC):
    """Bộ nhớ ngữ nghĩa dài hạn.

    **`user_id` luôn là id của một người — không bao giờ là id container.**
    Cả hai hiện thực (pgvector, Zep) đều theo hợp đồng này, và nó là hợp
    đồng chứ không phải quy ước đặt tên tình cờ.

    Từng không phải vậy: trường này nhận `workspace_id`, nên bộ nhớ thuộc
    về một workspace thay vì một người. Hai hệ quả đã đo được:

    * một người có hai workspace thì có hai bộ nhớ rời nhau, không cái nào
      biết cái kia;
    * hội thoại không có container — DM Mezon là một — **mất bộ nhớ hoàn
      toàn**, vì không có khoá nào để ghi vào.

    Bộ nhớ là thứ hệ thống biết về một *người*: thói quen, ràng buộc, quy
    trình của họ. Không có mảnh nào trong đó thuộc về một hộp chứa, nên
    chia nhỏ theo hộp chỉ tạo ra những khoảng mù không ai chủ đích tạo.

    `str` chứ không phải `UUID` là để phù hợp API của Zep (nó nhận chuỗi
    tuỳ ý làm id người dùng); người gọi truyền `str(user.id)`.
    """

    @abstractmethod
    async def ensure_user(self, user_id: str) -> bool:
        """`user_id`: id **người dùng**, dạng chuỗi. Xem docstring của lớp."""
        ...

    @abstractmethod
    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        ...

    @abstractmethod
    async def add_semantic_memories_batch(
        self,
        user_id: str,
        memories: list[dict],
    ) -> int:
        ...

    @abstractmethod
    async def search_semantic_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[SemanticMemoryResult]:
        ...


class FallbackSemanticMemoryProvider(SemanticMemoryProvider):

    def __init__(
        self,
        db: AsyncSession,
        primary: SemanticMemoryProvider | None = None,
        fallback: SemanticMemoryProvider | None = None,
    ):
        # **pgvector là chính, Zep là dự phòng** — đảo lại so với trước.
        #
        # Đo tại 2026-08-27 trên cùng một bộ nhớ ("khi tôi remote thì phải
        # check-in Slack…"):
        #
        #   pgvector  'hôm nay tôi remote' → 1   'làm việc từ xa' → 1
        #   Zep       'hôm nay tôi remote' → 0   'check-in Slack' → 0
        #
        # Zep nhận ghi (202 Accepted) nhưng không tìm ra, kể cả một chuỗi
        # con có trong chính nội dung, kể cả sau vài phút. Ghi bất đồng bộ
        # nghĩa là bộ nhớ vừa dạy không đọc lại được ngay — mà đó chính là
        # tình huống dùng thật: người dùng dạy một quy trình rồi hỏi lại.
        #
        # Đây là phép đo DESIGN 11.3 đặt ra cho Zep, và kết quả ngược với
        # giả định của nó: pgvector không kém hơn, Zep mới là thứ không trả
        # về gì. Zep giữ ở vị trí dự phòng chứ không gỡ — đảo một dòng là
        # đủ để thử lại khi nó được cấu hình đúng.
        if primary is None:
            from app.services.pgvector_memory_provider import PgVectorMemoryProvider
            primary = PgVectorMemoryProvider(db=db)
        if fallback is None:
            from app.services.zep_memory import ZepMemoryProvider
            fallback = ZepMemoryProvider()
        self._primary = primary
        self._fallback = fallback

    async def _try_fallback(self, method: str, *args, **kwargs):
        try:
            meth = getattr(self._primary, method)
            return await meth(*args, **kwargs)
        except SemanticMemoryUnavailable:
            logger.warning(
                "PgVector %s failed — falling back to Zep", method,
            )
            fallback_meth = getattr(self._fallback, method)
            return await fallback_meth(*args, **kwargs)

    async def ensure_user(self, user_id: str) -> bool:
        return await self._try_fallback("ensure_user", user_id=user_id)

    async def add_semantic_memory(
        self,
        user_id: str,
        category: str,
        content: str,
        confidence: float,
        expected_lifetime: str,
    ) -> bool:
        return await self._try_fallback(
            "add_semantic_memory",
            user_id=user_id,
            category=category,
            content=content,
            confidence=confidence,
            expected_lifetime=expected_lifetime,
        )

    async def add_semantic_memories_batch(
        self,
        user_id: str,
        memories: list[dict],
    ) -> int:
        return await self._try_fallback(
            "add_semantic_memories_batch",
            user_id=user_id,
            memories=memories,
        )

    async def search_semantic_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
        min_score: float | None = None,
    ) -> list[SemanticMemoryResult]:
        return await self._try_fallback(
            "search_semantic_memories",
            user_id=user_id,
            query=query,
            limit=limit,
            min_score=min_score,
        )


def get_semantic_memory_provider(db: AsyncSession) -> SemanticMemoryProvider:
    return FallbackSemanticMemoryProvider(db=db)
