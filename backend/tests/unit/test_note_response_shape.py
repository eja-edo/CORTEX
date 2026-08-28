"""
`NoteService.to_response` / `to_summary_response` phải dựng đủ mọi trường
schema đòi.

Đây là một lỗi đã xảy ra, không phải giả định. Khi `project_id` được thêm
vào `NoteResponse`, hai hàm dựng response không được cập nhật theo. Kết quả
**không phải** một lỗi lúc khởi động mà là:

    POST /api/notes  →  ghi chú được ghi vào DB, commit xong
                     →  serialize response ném ValidationError
                     →  500

Người dùng bấm "Ghi chú mới", không thấy gì xuất hiện, và ghi chú *đã* nằm
trong DB. Không có gì trên màn hình nói ra điều đó, và bấm lại sẽ tạo bản
thứ hai. Lỗi sau khi ghi thành công là loại tệ nhất trong nhóm này.

Test này rẻ và bắt đúng loại trôi đó: thêm một trường bắt buộc vào schema
mà quên hàm dựng thì nó đỏ ngay.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from app.models import Note
from app.schemas import NoteResponse, NoteSummary
from app.services.notes import NoteService


def _note(**overrides) -> Note:
    base = dict(
        id=uuid4(),
        user_id=uuid4(),
        project_id=uuid4(),
        parent_note_id=None,
        title="Ghi chú",
        content="# Ghi chú",
        content_type="markdown",
        position={"x": 0, "y": 0},
        size={"width": 200, "height": 200},
        style={"color": "yellow"},
        version=1,
        is_deleted=False,
        created_at=datetime(2026, 8, 26, 10, 0, 0),
        updated_at=datetime(2026, 8, 26, 10, 0, 0),
    )
    base.update(overrides)
    return Note(**base)


@pytest.fixture
def service() -> NoteService:
    # Cả hai hàm dựng là thuần: chúng đọc thuộc tính và trả một model. Không
    # cần session thật, và một session giả sẽ chỉ che mất điều đó.
    return NoteService(session=None)


def test_to_response_builds_a_valid_schema(service):
    response = service.to_response(_note())
    assert isinstance(response, NoteResponse)
    assert response.project_id is not None


def test_to_summary_response_builds_a_valid_schema(service):
    summary = service.to_summary_response(_note(), content_override="xem trước")
    assert isinstance(summary, NoteSummary)
    assert summary.project_id is not None


def test_a_note_with_no_container_at_all_still_serialises(service):
    """Ghi chú cũ chưa backfill, hoặc một hàng bị gỡ dự án (`ON DELETE SET
    NULL`). Cả hai trường container đều nullable, nên response phải dựng
    được — không thì một hàng dữ liệu cũ làm hỏng cả danh sách."""
    note = _note(project_id=None)
    assert service.to_response(note).project_id is None
    assert service.to_summary_response(note).project_id is None


def test_every_required_response_field_has_a_builder(service):
    """Khoá chiều ngược lại: schema thêm trường bắt buộc mà hàm dựng quên
    thì test này đỏ, thay vì `POST /api/notes` đỏ sau khi đã ghi."""
    built = service.to_response(_note()).model_dump()
    required = {
        name for name, field in NoteResponse.model_fields.items() if field.is_required()
    }
    assert required <= set(built)
