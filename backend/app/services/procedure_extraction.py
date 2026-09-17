"""Biến bộ nhớ `routine` thô thành `Procedure` có cấu trúc.

Chạy **có điều kiện**: chỉ khi vòng trích xuất vừa sinh ra ít nhất một bộ
nhớ `category == "routine"`. Với mọi vòng khác, chi phí là con số không.

Đó là lý do nó là một lời gọi riêng thay vì thêm một khoá nữa vào prompt
trích xuất (cách `tasks` đang làm). Routine hiếm; prompt trích xuất thì
chạy mỗi 20 tin nhắn và đã dài. Một prompt riêng, chỉ làm một việc, trên
đầu vào đã biết chắc là routine, vừa rẻ hơn tính trung bình vừa dễ đúng
hơn — nó không phải dạy lại "routine là gì" lần thứ hai.
"""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import GenerationConfig, Message
from app.ai.loaders.prompt_loader import load
from app.models import ProcedureSource
from app.services.memory_categories import CATEGORY_ROUTINE
from app.services.procedures import ProcedureService, _normalise_steps
from app.utils.logger import get_logger

logger = get_logger(__name__)

_model_client = ModelClient()

STRUCTURING_PROMPT = load("memory/procedure_structuring.md")

# Trên ngưỡng này, trigger mới được coi là **cùng một quy trình** với một
# quy trình đã có, và ta cập nhật thay vì tạo bản sao.
#
# Cao hơn hẳn `MIN_TRIGGER_SCORE` (0.70, dùng để khớp một lượt nói với một
# quy trình): ở đây hai vế đều là trigger do cùng một prompt sinh ra cho
# cùng một hoàn cảnh, nên chúng gần như trùng khớp khi thật sự trùng. Đặt
# thấp sẽ gộp nhầm hai quy trình khác nhau của cùng một người ("trước buổi
# demo" và "trước buổi họp") thành một, và mất hẳn một cái.
SAME_PROCEDURE_SCORE = 0.90


def _parse(raw: str) -> dict | None:
    """Bóc JSON khỏi câu trả lời, chấp nhận cả khi model bọc nó trong văn xuôi."""
    if not raw:
        return None
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        logger.warning("Procedure structuring: JSON hỏng (%s)", exc)
        return None
    return data if isinstance(data, dict) else None


async def structure_routine(routine_text: str) -> dict | None:
    """Tách một câu routine thành {title, trigger, steps}.

    Trả `None` khi không tách được — gọi bên trên phải coi đó là "không tạo
    quy trình nào", chứ không phải lỗi: bộ nhớ `routine` gốc vẫn còn nguyên
    và agent vẫn đọc được nó như trước.
    """
    if not routine_text or not routine_text.strip():
        return None

    try:
        _, response = await _model_client.generate(
            [Message(role="user", content=routine_text.strip())],
            GenerationConfig(
                system_instruction=STRUCTURING_PROMPT,
                temperature=0.0,
                max_output_tokens=800,
            ),
            tools=None,
        )
    except Exception as exc:
        logger.warning("Procedure structuring: lời gọi model hỏng (%s)", exc)
        return None

    data = _parse((response.content if response else "") or "")
    if not data:
        return None

    trigger = (data.get("trigger") or "").strip()
    steps = data.get("steps")
    if not trigger or not isinstance(steps, list) or not steps:
        # Câu trả lời rỗng là kết quả hợp lệ mà prompt có nói tới: văn bản
        # không thật sự mô tả một quy trình lặp lại.
        logger.info("Procedure structuring: không phải quy trình, bỏ qua")
        return None

    return {
        "title": (data.get("title") or trigger)[:255],
        "trigger": trigger,
        "steps": steps,
    }


async def sync_from_memories(
    db: AsyncSession, user_id: UUID, memories: list[dict]
) -> list[UUID]:
    """Tạo `Procedure` cho mỗi bộ nhớ `routine` mới trong lô này.

    Không bao giờ ném lỗi ra ngoài: đây là phần làm giàu chạy sau khi bộ
    nhớ đã được lưu an toàn. Hỏng ở đây phải mất một quy trình, không được
    mất cả vòng trích xuất.
    """
    routines = [
        m for m in memories
        if isinstance(m, dict) and m.get("category") == CATEGORY_ROUTINE and m.get("content")
    ]
    if not routines:
        return []

    service = ProcedureService(db)
    created: list[UUID] = []

    for memory in routines:
        try:
            structured = await structure_routine(memory["content"])
            if not structured:
                continue

            existing = await service.match(
                user_id, structured["trigger"], min_score=SAME_PROCEDURE_SCORE
            )
            if existing is not None:
                procedure, score = existing
                # Cùng hoàn cảnh, phát biểu lại: cập nhật các bước thay vì
                # tạo bản sao. Hai quy trình cùng trigger sẽ tranh nhau ở
                # `match()` và người dùng thấy một trong hai một cách ngẫu
                # nhiên.
                procedure.steps = _normalise_steps(structured["steps"])
                procedure.title = structured["title"]
                logger.info(
                    "Procedure cập nhật: %s (trùng trigger, score=%.4f)",
                    procedure.id, score,
                )
                continue

            procedure = await service.create(
                user_id=user_id,
                title=structured["title"],
                trigger_text=structured["trigger"],
                steps=structured["steps"],
                source=ProcedureSource.USER_STATED,
                confidence=float(memory.get("confidence") or 0.9),
            )
            created.append(procedure.id)
        except Exception as exc:
            logger.warning(
                "Không dựng được procedure từ routine %r: %s",
                str(memory.get("content"))[:60], exc,
            )

    return created
