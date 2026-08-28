"""Agent tools — what the agent is allowed to reach for.

**Registration is the freeze switch.** `docs/DESIGN.md` mục 11.2 gỡ một tool
khỏi đường chính bằng cách bỏ nó khỏi registry và **giữ nguyên tệp**; hồi
sinh là chuyển một dòng từ `FROZEN_TOOLS` sang `LIVE_TOOLS`. Không xoá tệp,
không comment-out thân hàm, không thư mục `_deprecated/` — cả ba đều làm
hồi sinh đắt hơn và làm codebase khó đọc hơn.

Hai danh sách đều được import: giữ import của phần đóng băng là chủ ý, vì
nó là thứ khiến "bật lại" thật sự chỉ tốn một dòng, và vì một import gãy sẽ
lộ ra ngay ở CI thay vì lộ ra lúc hồi sinh sáu tháng sau (11.1 — code đóng
băng *mục dần*).

Mỗi tool là một đường agent có thể đi sai, nên ngân sách ~8 ở mục 9.2 là
một ràng buộc thật: thêm cái thứ chín phải trả lời được P5 — nó làm agent
quyết định *đúng hơn*, hay chỉ làm agent *nói nhiều hơn*?
"""

from app.ai.agents.tool_registry import get_tool_registry

# ── Đang sống ────────────────────────────────────────────────────────────
from app.ai.tools.ask_user_choice import ASK_USER_CHOICE_DEFINITION
from app.ai.tools.confirm_task import CONFIRM_TASK_DEFINITION
from app.ai.tools.create_schedule import CREATE_SCHEDULE_DEFINITION
from app.ai.tools.create_project import CREATE_PROJECT_DEFINITION
from app.ai.tools.create_task import CREATE_TASK_DEFINITION
from app.ai.tools.get_project_tasks import GET_PROJECT_TASKS_DEFINITION
from app.ai.tools.get_schedules import GET_SCHEDULES_DEFINITION
from app.ai.tools.get_today import GET_TODAY_DEFINITION
from app.ai.tools.list_pending_tasks import LIST_PENDING_TASKS_DEFINITION
from app.ai.tools.list_projects import LIST_PROJECTS_DEFINITION
from app.ai.tools.move_task import MOVE_TASK_DEFINITION
from app.ai.tools.update_schedule import UPDATE_SCHEDULE_DEFINITION

# ── Đóng băng (DESIGN 11.3) — import giữ nguyên, không đăng ký ───────────
from app.ai.tools.create_note import CREATE_NOTE_DEFINITION
from app.ai.tools.deep_research import DEEP_RESEARCH_DEFINITION
from app.ai.tools.extract_memory import EXTRACT_MEMORY_DEFINITION
from app.ai.tools.get_notifications import GET_NOTIFICATIONS_DEFINITION
from app.ai.tools.neural_search import NEURAL_SEARCH_DEFINITION
from app.ai.tools.propose_plan import PROPOSE_PLAN_DEFINITION
from app.ai.tools.revert_action import REVERT_ACTION_DEFINITION
from app.ai.tools.search_knowledge import SEARCH_KNOWLEDGE_DEFINITION
from app.ai.tools.search_notes import SEARCH_NOTES_DEFINITION
from app.ai.tools.summarize_asset import SUMMARIZE_ASSET_DEFINITION
from app.ai.tools.update_note import UPDATE_NOTE_DEFINITION
from app.ai.tools.web_fetch import WEB_FETCH_DEFINITION
from app.ai.tools.web_search import WEB_SEARCH_DEFINITION


LIVE_TOOLS = [
    # Việc — bề mặt sản phẩm.
    CREATE_TASK_DEFINITION,
    LIST_PENDING_TASKS_DEFINITION,
    CONFIRM_TASK_DEFINITION,
    # Dự án (DESIGN 9.2). `list_projects` là cửa vào: agent phải khớp thứ
    # người dùng nói với một dự án có thật trước khi thao tác. Cả bốn dùng
    # chung quy tắc giải `project_ref` ở `project_ref.py` — khớp nhiều thì
    # hỏi, không khớp thì liệt kê, không bao giờ đoán (P7).
    LIST_PROJECTS_DEFINITION,
    GET_PROJECT_TASKS_DEFINITION,
    MOVE_TASK_DEFINITION,
    CREATE_PROJECT_DEFINITION,
    # Hôm nay — câu trả lời cho "giờ tôi nên làm gì".
    GET_TODAY_DEFINITION,
    # Lịch: khung thời gian, không phải cấu trúc dự án (QĐ-2). Vẫn cần vì
    # `is_user_busy` và `find_free_slots` đọc từ đây.
    GET_SCHEDULES_DEFINITION,
    CREATE_SCHEDULE_DEFINITION,
    UPDATE_SCHEDULE_DEFINITION,
    # Hỏi lại thay vì đoán — chỗ dựa của quy tắc giải `project_ref` (9.2):
    # khớp nhiều tên thì hỏi, không khớp thì liệt kê, không bao giờ đoán (P7).
    ASK_USER_CHOICE_DEFINITION,
    # Hoàn tác. Đã đóng băng nhầm một lần với lý do "phục vụ các tool đã
    # đóng băng" — sai: nó phục vụ `task.create/update/complete`,
    # `schedule.*` và cả hai command dự án, tất cả đều đang sống. Không có
    # nó thì mọi `revert_handler` trong `app/commands/handlers/` là code
    # không ai gọi được, và câu "hoàn tác" của người dùng không có đường
    # nào chạy.
    REVERT_ACTION_DEFINITION,
    # Ghi chú, Bản ghi, Thông báo — ba bề mặt này ở lại nav, nên tool của
    # chúng phải sống cùng. Một bề mặt người dùng nhìn thấy mà agent không
    # chạm được là kiểu hỏng khó hiểu nhất từ phía họ: màn hình bảo có, trợ
    # lý bảo không. Quy tắc từ đây: **tool sống hay chết theo bề mặt của
    # nó**, không theo một danh sách riêng dễ trôi.
    SEARCH_NOTES_DEFINITION,
    CREATE_NOTE_DEFINITION,
    UPDATE_NOTE_DEFINITION,
    SEARCH_KNOWLEDGE_DEFINITION,
    SUMMARIZE_ASSET_DEFINITION,
    GET_NOTIFICATIONS_DEFINITION,
    # Đường **đọc** của bộ nhớ dài hạn. Đóng băng nhầm một lần với lý do
    # "phục vụ Zep đã đóng băng" — sai: `pgvector_memory_provider` mới là
    # thứ đang chạy, Zep chỉ là provider thay thế chưa chứng minh giá trị.
    #
    # Hậu quả của lần cắt đó đúng như một pipeline một chiều sẽ gây ra:
    # `extract_and_store` vẫn ghi bộ nhớ sau mỗi vài tin nhắn, còn đây là
    # **đường duy nhất** gọi `search_semantic_memories` — nên không gì từng
    # đọc lại. Người dùng dạy một quy trình hôm nay, hôm sau hỏi thì agent
    # không biết gì.
    EXTRACT_MEMORY_DEFINITION,
]

# Mỗi mục dưới đây phục vụ một bề mặt đã gỡ khỏi nav hoặc một service đã gỡ
# khỏi compose mặc định. Điều kiện hồi sinh của từng bề mặt nằm ở DESIGN
# 11.3; tool theo bề mặt của nó, không hồi sinh riêng.
FROZEN_TOOLS = [
    WEB_SEARCH_DEFINITION,        # searxng — sau `--profile search`
    NEURAL_SEARCH_DEFINITION,     # unsearch — sau `--profile search`
    DEEP_RESEARCH_DEFINITION,     # searxng + unsearch
    WEB_FETCH_DEFINITION,         # đi kèm bộ web
    PROPOSE_PLAN_DEFINITION,      # `/planning` không có mục nav nào
]


def register_all_tools() -> None:
    """Đăng ký phần đang sống. `FROZEN_TOOLS` cố ý không đi qua đây."""
    registry = get_tool_registry()

    for tool_def in LIVE_TOOLS:
        registry.register(
            name=tool_def["name"],
            description=tool_def["description"],
            schema=tool_def["schema"],
            handler=tool_def["handler"],
            input_model=tool_def.get("input_model"),
        )


# Auto-register on import
register_all_tools()

__all__ = [
    "register_all_tools",
    "get_tool_registry",
    "LIVE_TOOLS",
    "FROZEN_TOOLS",
]
