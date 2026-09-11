"""Mức can thiệp cho **hội thoại** — cùng thang mà Attention Gate dùng.

Cortex phải trả lời câu "việc này có đáng làm phiền người dùng không, và ở
mức nào" ở hai bề mặt. Trước file này, hai bề mặt trả lời bằng hai cách
hoàn toàn khác nhau:

    kênh thông báo   code tất định — reason catalog, feedback loop,
                     dedup, quiet hours; giải thích được; tự học
    agent trong chat 644 từ prompt ("low stakes vs high stakes");
                     không biết gì về ba lần người dùng vừa bỏ qua

Đo được: `app/ai/` không có một dòng nào chạm tới `attention_gate`,
`reason_key` hay `feedback_loop`.

Hệ quả thấy được ở cả hai chiều. Người dùng bỏ qua nhắc `task.overdue` ba
lần, Feedback Loop hạ nó xuống và kênh thông báo im bớt — nhưng mở chat lên
agent vẫn sốt sắng đúng như cũ. Ngược lại, người dùng nói "thôi không cần"
năm lần trong chat thì không gì được ghi lại, vì vòng học chỉ ăn tín hiệu
từ nút dismiss trên notification — trong khi chat mới là nơi họ ở nhiều
nhất.

**Khác Gate đúng một bước: không hỏi "người dùng có rảnh không".**

Gate chạy năm bước; hàm ở đây chạy bốn, cố ý bỏ bước busy/quiet-hours.
Thông báo là *đẩy* — nó chen vào giờ của người dùng, nên phải hỏi họ có
đang bận không. Hội thoại là *kéo* — họ vừa gõ một câu cho Cortex. Ai mở
chat lúc 11 giờ đêm là đang chọn nói chuyện lúc 11 giờ đêm; im lặng vì
"ngoài giờ" ở đây là trả lời sai câu hỏi họ vừa hỏi.

Dedup và supersession cũng không áp: chúng khoá theo `(item_id,
reason_key)` của một item cụ thể đang được nhắc, còn đây là câu hỏi
"giọng nào cho loại đề xuất này", không gắn với một hàng nào.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AttentionLevel
from app.services.attention_reason_catalog import base_level_for
from app.services.feedback_loop import apply_downgrade, dismiss_count_async
from app.services.user_preferences import get_preferences_async, is_reason_disabled
from app.utils.logger import get_logger

if TYPE_CHECKING:
    from app.models import AttentionItemType

logger = get_logger(__name__)


# Mỗi mức nói cho agent một *giọng*, không phải một mệnh lệnh cứng. Bảng này
# đi thẳng vào prompt, nên nó phải đọc được như hướng dẫn cho người.
LEVEL_GUIDANCE: dict[AttentionLevel, str] = {
    AttentionLevel.ACT: (
        "làm luôn, rồi báo lại kết quả trong một dòng"
    ),
    AttentionLevel.ASK: (
        "hỏi trước khi làm — dùng ask_user_choice nếu câu trả lời nằm trong "
        "một tập nhỏ"
    ),
    AttentionLevel.RECOMMEND: (
        "đề xuất kèm một mặc định cụ thể, gói trong một câu; đừng chặn cuộc "
        "trò chuyện để chờ trả lời"
    ),
    AttentionLevel.INFORM: (
        "nhắc một dòng rồi đi tiếp; không hỏi"
    ),
    AttentionLevel.SILENT: (
        "không nhắc gì cả — người dùng đã cho biết họ không muốn loại này"
    ),
}


async def conversational_level(
    session: AsyncSession, user_id: UUID, reason_key: str
) -> AttentionLevel:
    """Mức can thiệp cho `reason_key` với người này, trong hội thoại.

    Bốn bước, cùng dữ liệu mà Gate dùng:

    1. người dùng đã tắt hẳn loại này chưa (`disabled_reason_keys`);
    2. mức nền của loại việc (`attention_reason_catalog`);
    3. hạ bậc theo số lần họ đã bỏ qua (`feedback_loop`);
    4. — bước "có bận không" của Gate **không** chạy ở đây, xem docstring
       module.

    Không bao giờ ném lỗi: mức can thiệp là thứ tinh chỉnh giọng nói, không
    phải điều kiện để trả lời được. Hỏng thì rơi về mức nền của catalog,
    tức là hành vi như trước khi file này tồn tại.
    """
    try:
        prefs = await get_preferences_async(session, user_id)
        if is_reason_disabled(prefs, reason_key):
            return AttentionLevel.SILENT

        level = base_level_for(reason_key)
        dismissals = await dismiss_count_async(session, user_id, reason_key)
        return apply_downgrade(level, dismissals)
    except Exception as exc:
        logger.warning(
            "Không tính được mức can thiệp cho %r (non-fatal): %s", reason_key, exc
        )
        try:
            return base_level_for(reason_key)
        except Exception:
            return AttentionLevel.RECOMMEND


async def record_chat_dismissal(
    session: AsyncSession,
    user_id: UUID,
    *,
    reason_key: str,
    item_type: "AttentionItemType",
    item_id: UUID,
) -> bool:
    """Ghi lại việc người dùng **từ chối** một đề xuất trong hội thoại.

    Đây là nửa còn lại của vòng học, và nó từng thiếu hẳn. Trước hàm này,
    `feedback_loop` chỉ ăn được tín hiệu từ nút dismiss trên một
    notification — trong khi chat mới là nơi người dùng ở nhiều nhất. Hệ
    quả: họ nói "thôi không cần" mười lần trong chat và không gì được ghi
    lại, nên mức can thiệp không bao giờ hạ.

    **Chỉ gọi từ một tín hiệu tất định.** Không suy ra "người dùng từ chối"
    từ câu chữ, và không để model tự khai bằng một tool: đợt
    `mark_procedure_step` đã đo được rằng model sẵn sàng khai một điều nó
    suy diễn ra (nó đọc "quá giờ" thành "đã xong" rồi ghi vào DB). Một vòng
    học ăn dữ liệu do model phán đoán sẽ học chính những phán đoán sai đó.

    Tín hiệu đạt chuẩn đó hiện có một: `task.reject` — người dùng bấm/nói
    "không" với một việc bộ trích xuất đoán ra, và trạng thái task chuyển
    `pending_confirm → rejected`. Đó là hành động của con người, không phải
    suy luận của model.

    Ghi cả phần "đã đề xuất" lẫn phần "bị từ chối" trong một hàng, vì ở chat
    không ai ghi phần đầu: agent nói ra đề xuất trong câu trả lời, không qua
    `record_surface`. Cố tách thành hai hàng sẽ tạo ra một hàng
    `no_response` vĩnh viễn không ai đóng.

    Không bao giờ ném lỗi: đây là việc ghi nhận bên lề một thao tác người
    dùng vừa làm thành công. Mất một điểm dữ liệu của vòng học còn hơn làm
    thao tác đó thất bại.
    """
    from app.models import AttentionChannel, AttentionLog, AttentionResponse

    try:
        level = await conversational_level(session, user_id, reason_key)
        session.add(
            AttentionLog(
                user_id=user_id,
                item_type=item_type,
                item_id=item_id,
                reason_key=reason_key,
                level=level,
                # `IN_APP` là *bề mặt quyết định*, không phải đường giao —
                # xem docstring của `AttentionChannel`. Hội thoại (web hay
                # Mezon) đều là in-app theo nghĩa đó.
                channel=AttentionChannel.IN_APP,
                response=AttentionResponse.DISMISSED,
                responded_at=datetime.utcnow(),
            )
        )
        await session.flush()
        logger.info(
            "Ghi từ chối từ hội thoại: reason=%s item=%s level=%s",
            reason_key, item_id, level.value,
        )
        return True
    except Exception as exc:
        logger.warning(
            "Không ghi được phản hồi từ hội thoại cho %r (non-fatal): %s",
            reason_key, exc,
        )
        return False


async def levels_for(
    session: AsyncSession, user_id: UUID, reason_keys: list[str]
) -> dict[str, AttentionLevel]:
    """`conversational_level` cho nhiều reason_key một lượt."""
    return {
        key: await conversational_level(session, user_id, key) for key in reason_keys
    }
