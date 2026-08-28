"""
Prompt hệ thống phải khớp danh sách tool thật.

Đây là một lỗi đã xảy ra, không phải một lỗi giả định. Sau khi mục 11 đóng
băng 13 tool, `assistant_system.md` vẫn liệt kê bảy tool không còn tồn tại
(`search_notes`, `create_note`, `extract_memory`, …) và **không** liệt kê
một tool việc nào — kể cả `create_task`, thứ mà cả sản phẩm xoay quanh. Mục
MEMORY & CONTEXT còn viết *"You MUST call `extract_memory`"* cho một tool đã
gỡ khỏi registry.

Hậu quả không phải một exception mà là một agent kém đi một cách im lặng:
nó gọi tool không tồn tại, nhận `Tool not found`, tiêu một lượt, rồi bịa ra
câu trả lời — hoặc nó không biết mình *có* `list_projects` và trả lời câu
hỏi về dự án bằng phỏng đoán.

Hai khẳng định dưới đây rẻ và bắt được đúng loại trôi đó.
"""

from pathlib import Path

import pytest

from app.ai.tools import FROZEN_TOOLS, LIVE_TOOLS

PROMPT_PATH = (
    Path(__file__).resolve().parents[2] / "app" / "ai" / "prompts" / "system" / "assistant_system.md"
)


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


@pytest.mark.parametrize("tool", [t["name"] for t in FROZEN_TOOLS])
def test_a_frozen_tool_is_never_named_in_the_prompt(tool: str, prompt_text: str):
    """Bảo agent gọi một tool đã gỡ khỏi registry là tiêu một lượt để nhận
    `Tool not found` — và với một model, một lượt hỏng thường kết thúc bằng
    một câu bịa, không phải bằng một lời xin lỗi."""
    assert tool not in prompt_text, (
        f"`{tool}` đã đóng băng (app/ai/tools/__init__.py) nhưng prompt vẫn "
        f"nhắc tên nó. Gỡ khỏi prompt, hoặc chuyển tool về LIVE_TOOLS."
    )


@pytest.mark.parametrize("tool", [t["name"] for t in LIVE_TOOLS])
def test_every_live_tool_is_named_in_the_prompt(tool: str, prompt_text: str):
    """Ngược lại cũng hỏng theo cách im lặng: một tool có đăng ký nhưng
    prompt không nhắc tới thì model hiếm khi tự tìm ra nó, và nó trả lời
    bằng phỏng đoán thay vì bằng dữ liệu."""
    assert tool in prompt_text, (
        f"`{tool}` đang sống nhưng prompt không nhắc tới. Thêm vào mục "
        f"'Available tools' để agent biết nó tồn tại."
    )
