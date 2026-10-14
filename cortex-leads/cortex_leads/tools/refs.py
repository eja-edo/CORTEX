# port từ backend/app/ai/tools/project_ref.py (generalised)
"""Resolve a free-text reference to one candidate: exactly one match -> use it, several ->
ambiguous (list them), none -> not_found (list options). No fuzzy matching and no LLM: a "close
enough" guess is most confident exactly when it is wrong."""
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from cortex_leads.core.envelope import ErrorCode, ErrorInfo, ToolResult

MAX_LISTED = 20


def _norm(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s).strip().lower().split())


@dataclass(frozen=True)
class Resolution[T]:
    status: Literal["match", "ambiguous", "not_found"]
    match: T | None = None
    options: list[T] = field(default_factory=list)


def resolve[T](
    candidates: Sequence[T], query: str, *, keys: Callable[[T], Sequence[str]] = lambda c: [str(c)]
) -> Resolution[T]:
    """Levels, stopping at the first that hits: exact key, then key contains query."""
    q = _norm(query)
    exact = [c for c in candidates if q and q in {_norm(k) for k in keys(c)}]
    hits = exact or [c for c in candidates if q and any(q in _norm(k) for k in keys(c))]
    if len(hits) == 1:
        return Resolution("match", hits[0])
    if hits:
        return Resolution("ambiguous", options=hits[:MAX_LISTED])
    return Resolution("not_found", options=list(candidates[:MAX_LISTED]))


def unresolved(res: Resolution[Any], what: str, brief: Callable[[Any], Any]) -> ToolResult:
    """Standard envelope for the two unresolved branches."""
    options = [brief(o) for o in res.options]
    if res.status == "ambiguous":
        return ToolResult(
            status="ambiguous", data={"options": options},
            error=ErrorInfo(code=ErrorCode.AMBIGUOUS_REF),
            next_step=f"Nhiều {what} khớp; chọn một trong danh sách rồi gọi lại với mã chính xác.",
        )
    return ToolResult(
        status="not_found", data={"options": options},
        error=ErrorInfo(code=ErrorCode.NOT_FOUND),
        note=f"Không có {what} nào khớp — đừng đoán và đừng tự tạo.",
        next_step=f"Chỉ dùng {what} trong danh sách (nếu có).",
    )
