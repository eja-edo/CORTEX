"""
Định tuyến kênh theo phạm vi — `docs/DESIGN.md` mục 8.1.

Đây là **thứ duy nhất trong thiết kế tạo ra giá trị tập thể ở đúng chi phí
tập thể**: nhắc cấp dự án về channel chung của dự án, nhắc cá nhân về DM.
Nó gỡ chính lỗi cấu trúc đã giết hướng "bot nghe channel" (DESIGN 1.4) — ở
đó tập thể trả giá và cá nhân hưởng.

Tiêu chí nghiệm thu quan trọng nhất ở đây là một điều **không** xảy ra:
`attention_gate.py` không phải sửa một dòng nào. Gate quyết định *có nói
không*; đây quyết định *nói qua đâu* (P2).
"""

from uuid import uuid4

import pytest

from app.models import AttentionLevel
from app.services.attention_reason_catalog import (
    REASON_CATALOG,
    ReasonScope,
    scope_for,
)
from app.services.delivery.base import DeliveryPayload

CHANNEL = "1234567890"


def _payload(reason_key, extra=None) -> DeliveryPayload:
    return DeliveryPayload(
        notification_id=uuid4(),
        user_id=uuid4(),
        type="t",
        title="x",
        body="",
        payload=extra if extra is not None else {},
        reason_key=reason_key,
        attention_level=AttentionLevel.RECOMMEND,
    )


# ============================================================================
# Catalog
# ============================================================================


def test_only_the_two_project_predicates_carry_project_scope():
    """Danh sách này cố ý ngắn và cố ý được khoá lại.

    Mỗi reason được nâng lên `PROJECT` là một đường mới để Cortex đăng vào
    một channel cả nhóm đọc. Thêm cái thứ ba phải là một quyết định có chủ
    ý, không phải một dòng lọt qua review — nên test này liệt kê thay vì
    kiểm tính chất.
    """
    project_scoped = {
        key for key, meta in REASON_CATALOG.items() if meta.scope is ReasonScope.PROJECT
    }
    assert project_scoped == {"project.slipping", "project.will_miss"}


def test_an_unregistered_reason_defaults_to_personal_not_project():
    """Sai theo hướng ít ồn hơn (P7): một reason mới quên khai phạm vi đi
    về DM của một người, không phát nhầm vào channel chung."""
    assert scope_for("some.brand.new.reason") is ReasonScope.PERSONAL


@pytest.mark.parametrize(
    "reason_key",
    ["task.overdue", "task.at_risk", "task.stale", "day.plan", "schedule.starts_soon"],
)
def test_every_task_level_reason_stays_personal(reason_key):
    assert scope_for(reason_key) is ReasonScope.PERSONAL


# ============================================================================
# DeliveryPayload.project_channel_id
# ============================================================================


def test_a_project_reason_with_a_channel_routes_to_that_channel():
    payload = _payload("project.slipping", {"source_channel_id": CHANNEL})
    assert payload.project_channel_id == CHANNEL


def test_a_personal_reason_never_routes_to_a_channel_even_if_one_is_present():
    """Trường hợp dễ hỏng nhất: payload của một reason cá nhân tình cờ mang
    `source_channel_id` (ví dụ task thuộc một dự án có channel). Phạm vi —
    không phải sự có mặt của trường — mới là thứ quyết định."""
    payload = _payload("task.overdue", {"source_channel_id": CHANNEL})
    assert payload.project_channel_id is None


def test_a_project_without_a_channel_falls_back_to_the_dm():
    """Dự án cá nhân và dự án tạo tay có `source_channel_id = NULL`
    (DESIGN 3.1.1). Chúng về DM, và không cần nhánh riêng ở đâu cả."""
    assert _payload("project.slipping", {}).project_channel_id is None
    assert _payload("project.slipping", {"source_channel_id": None}).project_channel_id is None


def test_a_pass_through_notification_has_no_reason_and_no_channel():
    """Thông báo không qua Gate (`reason_key IS NULL`) — ví dụ Google
    Calendar bị thu hồi quyền — luôn là chuyện của một người."""
    assert _payload(None, {"source_channel_id": CHANNEL}).project_channel_id is None


def test_the_channel_id_reaches_the_adapter_as_a_string():
    """Bot nhận `mezon_channel_id` và đưa thẳng vào `sendToChannel`, nên
    kiểu phải là chuỗi kể cả khi payload lưu số."""
    payload = _payload("project.will_miss", {"source_channel_id": 1234567890})
    assert payload.project_channel_id == "1234567890"
