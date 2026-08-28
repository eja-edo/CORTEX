"""Bộ nhớ ngữ nghĩa khoá theo **người**, không theo container.

Đây là một hợp đồng đã từng bị vi phạm, không phải một lo ngại giả định.
`memory_extraction_service` từng truyền `conv.workspace_id` vào tham số
`user_id` của provider. Hai hệ quả, cả hai đều im lặng:

* một người có hai workspace thì có hai bộ nhớ rời nhau;
* hội thoại không có container (DM Mezon) **mất bộ nhớ hoàn toàn**.

Kiểu của tham số là `str`, nên không có gì ở tầng ngôn ngữ chặn việc truyền
nhầm một id khác — chỉ có test này. Nó đọc chính mã nguồn của hai nơi gọi
thay vì chạy chúng, vì thứ cần khoá là *biến nào được truyền vào*, và một
test hành vi sẽ xanh y hệt khi truyền nhầm id.
"""

import ast
import inspect
from pathlib import Path

import pytest

from app.services import memory_extraction_service
from app.ai.tools import extract_memory as extract_memory_tool
from app.services.semantic_memory_provider import SemanticMemoryProvider

MEMORY_METHODS = {
    "ensure_user",
    "add_semantic_memory",
    "add_semantic_memories_batch",
    "search_semantic_memories",
}

# Tên biến hợp lệ để truyền vào `user_id=`. Bất cứ thứ gì khác — nhất là
# thứ có "workspace" hay "project" trong tên — là hồi quy.
ALLOWED = {"memory_owner_id", "user_id", "owner_id"}


def _user_id_arguments(module) -> list[tuple[str, str]]:
    """(tên hàm được gọi, mã nguồn của đối số `user_id=`) cho mỗi lời gọi."""
    tree = ast.parse(Path(inspect.getfile(module)).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in MEMORY_METHODS:
            continue
        for kw in node.keywords:
            if kw.arg == "user_id":
                found.append((name, ast.unparse(kw.value)))
    return found


@pytest.mark.parametrize(
    "module", [memory_extraction_service, extract_memory_tool],
    ids=["ghi (memory_extraction_service)", "đọc (extract_memory tool)"],
)
def test_every_memory_call_passes_a_user_id(module):
    calls = _user_id_arguments(module)
    assert calls, f"{module.__name__} không còn gọi provider nào — test này đã lạc hậu"

    for method, argument in calls:
        root = argument.split(".")[0].replace("str(", "").strip("()")
        assert not any(bad in argument.lower() for bad in ("workspace", "project")), (
            f"{module.__name__} truyền {argument!r} vào {method}(user_id=...). "
            "Bộ nhớ khoá theo người; truyền id container sẽ chia bộ nhớ của "
            "một người thành nhiều mảnh và làm hội thoại không container mất "
            "bộ nhớ hoàn toàn."
        )
        assert root in ALLOWED, (
            f"{module.__name__} truyền {argument!r} vào {method}(user_id=...) — "
            f"tên không nằm trong {sorted(ALLOWED)}. Nếu đây thật sự là id "
            "người dùng, thêm tên vào ALLOWED; nếu không, đó là hồi quy."
        )


def test_the_contract_is_written_down_where_an_implementer_will_read_it():
    """Một hợp đồng chỉ sống trong test là hợp đồng người viết hiện thực
    tiếp theo không bao giờ thấy."""
    doc = (SemanticMemoryProvider.__doc__ or "").lower()
    assert "user_id" in doc
    assert "không bao giờ là id container" in doc
