"""Danh mục bộ nhớ ngữ nghĩa — một nguồn sự thật duy nhất.

Trước file này danh mục được khai ở ba nơi, và cả ba nói khác nhau:

    prompts/memory/semantic_extraction.md   project | preference | constraint |
                                            environment | decision_pattern | routine
    memory_extraction_prompt._RESPONSE_SHAPE  routine | preference | policy |
                                            fact | decision
    migration p0123456789l (comment cột)    project | preference | constraint |
                                            environment | decision_pattern

Cột là `String(30)` nên không lời gọi nào từng lỗi — nó chỉ **im lặng** sai.
Đo trên DB dev (2026-09-10), phân bố thật của `semantic_memories.category`:

    fact 6 | decision 2 | routine 2 | preference 2 | policy 1 | goal 1

Không một dòng nào mang `project`/`constraint`/`environment`/
`decision_pattern`. Nghĩa là `_RESPONSE_SHAPE` — dòng chốt cuối lượt user —
thắng tuyệt đối, tài liệu `semantic_extraction.md` bị bỏ qua hoàn toàn, và
model còn tự bịa thêm một danh mục thứ sáu (`goal`) không nơi nào khai.

Hệ quả không phải là log xấu: nó chặn mọi tính năng đọc bộ nhớ theo loại.
Không thể lọc `category='routine'` một cách tin cậy khi cùng một quy trình
có thể được lưu là `routine`, `policy` hay `fact` tuỳ lượt trích xuất.

Nên: khai một lần ở đây, và mọi chỗ khác *dẫn xuất* từ đây — prompt sinh ra
từ `categories_for_prompt()`, đường ghi đi qua `normalize_category()`.
"""

from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Tập chuẩn
# ---------------------------------------------------------------------------

CATEGORY_ROUTINE = "routine"
CATEGORY_PREFERENCE = "preference"
CATEGORY_CONSTRAINT = "constraint"
CATEGORY_GOAL = "goal"
CATEGORY_FACT = "fact"
CATEGORY_DECISION = "decision"

# Thứ tự ở đây là thứ tự xuất hiện trong prompt. Đặt `routine` trước vì nó
# là danh mục duy nhất mà một danh sách bước là *nội dung*, không phải rác —
# xem phần routine trong prompts/memory/semantic_extraction.md.
CANONICAL_CATEGORIES: tuple[str, ...] = (
    CATEGORY_ROUTINE,
    CATEGORY_PREFERENCE,
    CATEGORY_CONSTRAINT,
    CATEGORY_GOAL,
    CATEGORY_FACT,
    CATEGORY_DECISION,
)

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    CATEGORY_ROUTINE: (
        'quy trình lặp lại, dạng "khi <hoàn cảnh> thì tôi phải <các bước>". '
        "Giữ nguyên cả trigger lẫn mọi bước trong MỘT entry."
    ),
    CATEGORY_PREFERENCE: (
        "sở thích, thói quen, cách người dùng muốn được phục vụ "
        '("thích họp buổi sáng", "muốn trả lời ngắn gọn").'
    ),
    CATEGORY_CONSTRAINT: (
        "ràng buộc cứng hoặc quy định phải tuân — của bản thân hoặc của tổ "
        'chức ("không họp sau 18h", "công ty cấm dùng Drive cá nhân").'
    ),
    CATEGORY_GOAL: (
        "mục tiêu dài hạn người dùng đang theo đuổi "
        '("giảm 5kg trong 3 tháng", "thi IELTS 7.0 tháng 12").'
    ),
    CATEGORY_FACT: (
        "sự thật ổn định về người dùng và môi trường làm việc "
        '("làm ở team 5 người", "dự án Cortex deadline tháng 11").'
    ),
    CATEGORY_DECISION: (
        "quyết định đã chốt kèm lý do, thứ định hướng các lượt sau "
        '("chọn pgvector thay Zep vì Zep không trả về kết quả").'
    ),
}

# `fact` là đáy an toàn: một bộ nhớ phân loại sai vẫn tìm lại được bằng
# embedding, còn một bộ nhớ bị bỏ đi thì mất hẳn. Không bao giờ ném lỗi ở
# đường ghi chỉ vì model gọi tên một danh mục lạ.
DEFAULT_CATEGORY = CATEGORY_FACT

# Tên cũ → tên chuẩn. Ba nguồn ở docstring trên, cộng `unknown` mà
# `memory_extraction_service` gán cho bộ nhớ trả về dạng chuỗi trần.
_ALIASES: dict[str, str] = {
    # từ _RESPONSE_SHAPE cũ
    "policy": CATEGORY_CONSTRAINT,
    # từ semantic_extraction.md cũ / comment migration
    "project": CATEGORY_FACT,
    "environment": CATEGORY_FACT,
    "decision_pattern": CATEGORY_DECISION,
    # lưới an toàn của memory_extraction_service khi model trả chuỗi trần
    "unknown": DEFAULT_CATEGORY,
    # biến thể hay gặp
    "routines": CATEGORY_ROUTINE,
    "preferences": CATEGORY_PREFERENCE,
    "constraints": CATEGORY_CONSTRAINT,
    "goals": CATEGORY_GOAL,
    "facts": CATEGORY_FACT,
    "decisions": CATEGORY_DECISION,
    "procedure": CATEGORY_ROUTINE,
    "workflow": CATEGORY_ROUTINE,
    "rule": CATEGORY_CONSTRAINT,
    "objective": CATEGORY_GOAL,
}


def normalize_category(raw: str | None) -> str:
    """Đưa một danh mục bất kỳ về tập chuẩn.

    Không bao giờ ném lỗi và không bao giờ trả chuỗi rỗng — đường ghi bộ nhớ
    không được hỏng vì một cái tên lạ. Trường hợp không nhận ra được ghi log
    ở mức WARNING kèm giá trị gốc, để danh mục mới model hay bịa ra lộ ra ở
    log chứ không lộ ra ở một truy vấn trả về rỗng vài tuần sau.
    """
    if not raw:
        return DEFAULT_CATEGORY

    key = str(raw).strip().lower()
    if key in CANONICAL_CATEGORIES:
        return key

    mapped = _ALIASES.get(key)
    if mapped:
        return mapped

    logger.warning(
        "Danh mục bộ nhớ không nhận ra: %r → dùng %r. Nếu nó xuất hiện đều "
        "đặn, hoặc thêm alias hoặc nâng thành danh mục chuẩn trong "
        "app/services/memory_categories.py.",
        raw, DEFAULT_CATEGORY,
    )
    return DEFAULT_CATEGORY


def categories_for_prompt() -> str:
    '''Tập chuẩn dưới dạng union JSON: `"routine" | "preference" | ...`.

    `_RESPONSE_SHAPE` gọi hàm này thay vì viết tay danh sách, nên prompt
    không thể lệch khỏi thứ đường ghi chấp nhận nữa.
    '''
    return " | ".join(f'"{c}"' for c in CANONICAL_CATEGORIES)


def category_guide() -> str:
    """Bảng giải nghĩa từng danh mục, dùng trong prompt trích xuất."""
    return "\n".join(
        f"* `{name}` — {CATEGORY_DESCRIPTIONS[name]}" for name in CANONICAL_CATEGORIES
    )
