"""Danh mục bộ nhớ phải nói cùng một thứ ở mọi nơi.

Bug mà tệp này canh không phải một exception — nó là sự im lặng. Danh mục
được khai ở ba nơi (prompt trích xuất, JSON shape chốt lượt user, comment
của migration), cả ba nói khác nhau, cột là `String(30)` nên không lời gọi
nào từng lỗi, và DB dev tích được sáu tên khác nhau trước khi có ai nhìn.

Nên các test ở đây kiểm đúng cái đã hỏng: **ba nguồn có còn dẫn xuất từ một
chỗ không**, chứ không phải `normalize_category` có chạy không.
"""

import re
from pathlib import Path

import pytest

from app.services.memory_categories import (
    CANONICAL_CATEGORIES,
    CATEGORY_DESCRIPTIONS,
    DEFAULT_CATEGORY,
    _ALIASES,
    categories_for_prompt,
    normalize_category,
)


class TestNormalize:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # tên cũ của _RESPONSE_SHAPE
            ("policy", "constraint"),
            # tên cũ của semantic_extraction.md / comment migration
            ("project", "fact"),
            ("environment", "fact"),
            ("decision_pattern", "decision"),
            # lưới an toàn của memory_extraction_service
            ("unknown", "fact"),
            # tên chuẩn đi qua nguyên vẹn
            ("routine", "routine"),
            ("goal", "goal"),
        ],
    )
    def test_maps_every_historical_spelling(self, raw, expected):
        assert normalize_category(raw) == expected

    @pytest.mark.parametrize("raw", ["Routine", " GOAL ", "PREFERENCE"])
    def test_case_and_whitespace_insensitive(self, raw):
        assert normalize_category(raw) in CANONICAL_CATEGORIES

    @pytest.mark.parametrize("raw", [None, "", "   ", "danh_mục_model_tự_bịa"])
    def test_never_raises_never_returns_empty(self, raw):
        """Mất metadata còn hơn mất bộ nhớ — đường ghi không được chết."""
        assert normalize_category(raw) == DEFAULT_CATEGORY

    def test_every_alias_target_is_canonical(self):
        """Một alias trỏ tới tên không chuẩn sẽ tái tạo đúng bug ban đầu."""
        for old, new in _ALIASES.items():
            assert new in CANONICAL_CATEGORIES, f"alias {old!r} → {new!r} không chuẩn"

    def test_default_is_itself_canonical(self):
        assert DEFAULT_CATEGORY in CANONICAL_CATEGORIES

    def test_every_category_is_documented(self):
        """Một danh mục không có mô tả thì model không biết khi nào dùng nó."""
        assert set(CATEGORY_DESCRIPTIONS) == set(CANONICAL_CATEGORIES)


class TestThreeSourcesAgree:
    """Ba nơi từng bất đồng. Mỗi test dưới đây canh một nơi."""

    def test_json_shape_is_derived_not_handwritten(self):
        """Nguồn 1 — dòng chốt cuối lượt user, thứ model thật sự tuân theo."""
        from app.services.memory_extraction_prompt import response_shape

        shape = response_shape()
        assert categories_for_prompt() in shape
        for stale in ("policy", "decision_pattern", "environment"):
            assert f'"{stale}"' not in shape

    def test_extraction_prompt_lists_the_canonical_set(self):
        """Nguồn 2 — prompt hệ thống của bộ trích xuất."""
        prompt = Path("app/ai/prompts/memory/semantic_extraction.md").read_text(
            encoding="utf-8"
        )
        line = next(
            l for l in prompt.splitlines() if l.startswith('- "category": one of')
        )
        # chỉ phần sau "one of" — nếu không, chính chữ "category" ở đầu dòng
        # cũng lọt vào tập được so sánh
        listed = set(re.findall(r'"([a-z_]+)"', line.split("one of", 1)[1]))
        assert listed == set(CANONICAL_CATEGORIES)

    def test_migration_renames_match_the_alias_table(self):
        """Nguồn 3 — dữ liệu đã nằm trong DB.

        Migration dọn hàng cũ; `_ALIASES` dọn hàng mới. Hai bảng lệch nhau
        nghĩa là một spelling được sửa ở đường này và bỏ sót ở đường kia.
        """
        import importlib.util

        path = Path(
            "alembic/versions/aa01mem0cat1_normalize_semantic_memory_categories.py"
        )
        spec = importlib.util.spec_from_file_location("_mig_cat", path)
        mig = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mig)

        for old, new in mig._RENAMES.items():
            assert _ALIASES.get(old) == new, (
                f"migration đổi {old!r}→{new!r} nhưng normalize_category cho "
                f"{_ALIASES.get(old)!r}"
            )
