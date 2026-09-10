"""Phép kiểm trích dẫn của `procedure.mark_step`.

Vì sao nó tồn tại — thí nghiệm đối chứng 2026-09-10, cùng một câu người
dùng ("hôm nay tôi remote", không báo xong bất cứ gì):

    bước "Daily — trước 9h sáng", chạy lúc 21h  → model TỰ đánh dấu xong
    bước "Daily" (không kèm giờ)                → model không đánh dấu

Model diễn giải *"đã quá giờ"* thành *"đã làm xong"* rồi ghi vào DB rằng
người dùng đã làm một việc họ chưa hề nhắc tới. Prompt lúc đó đã nói "chỉ
khi họ báo" — và bị bỏ qua. Nên phép kiểm nằm ở code, cùng lối với
`source_quote` của `app.services.task_extraction`: model trích dẫn, code
đối chiếu.

Các test dưới đây kiểm phần chuẩn hoá. Phần đối chiếu với DB nằm ở
`tests/integration/test_procedure_quote_guard.py`.
"""

import pytest

from app.commands.handlers.procedure_commands import _normalise_quote


class TestNormalise:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("  Daily xong rồi  ", "daily xong rồi"),
            ("Daily   xong\nrồi", "daily xong rồi"),
            ("DAILY XONG RỒI", "daily xong rồi"),
            ("", ""),
            ("   ", ""),
        ],
    )
    def test_case_and_whitespace(self, raw, expected):
        assert _normalise_quote(raw) == expected

    def test_none_is_empty_not_a_crash(self):
        """Đường ghi không được chết vì một trường thiếu."""
        assert _normalise_quote(None) == ""

    def test_vietnamese_diacritics_are_kept(self):
        """Không bỏ dấu — mục đích là chặn bịa đặt, không phải nới lỏng.

        Bỏ dấu sẽ làm "đã xong" khớp với "da xong" và mở lại đúng khoảng
        trống mà phép kiểm này sinh ra để đóng.
        """
        assert _normalise_quote("Đã xong") == "đã xong"
        assert _normalise_quote("Đã xong") != "da xong"

    def test_punctuation_is_kept(self):
        assert _normalise_quote("xong rồi!") == "xong rồi!"
