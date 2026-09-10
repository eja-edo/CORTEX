"""
Context schemas for Cortex.

⚠️ 2026-08-06: Adapted from the Milestone 1.7 plan to match what the system
actually does today, not the plan's invented shape. The frontend sends a
free-form `context: dict | None` per chat request with (at most) three keys:
`pills` (list of `{"text": ..., "source": ...}`), `page` (dict), `runtime`
(dict) — see `app/ai/agents/conversation_service.py::_inject_context_into_text`.
There is no `view`/`ViewType`/`CurrentObject` contract anywhere in the
frontend payload, so this module does NOT invent one (a strict schema for
fields the frontend doesn't actually send would just raise ValidationError
on real traffic). `pills`/`page`/`runtime` are kept here as loosely-typed
passthroughs; `project`/`recent_notes`/`recent_schedules` are the genuinely
new, DB-sourced sections `ContextService` adds.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ContextPill(BaseModel):
    """User-provided or system-generated context snippet (frontend `pills[]`)."""
    text: str
    source: str = Field(default="user", description="user, system, or agent")


class ProjectContext(BaseModel):
    """Dự án đang mở, nếu có."""
    project_id: UUID
    project_name: str
    # Không có `role`: `ProjectMember` cố ý không có cột đó (QĐ-1) — "ai
    # được đọc tài liệu" và "ai chịu trách nhiệm việc" là hai câu hỏi khác
    # nhau, và ba mức owner/editor/viewer không trả lời câu thứ hai.
    member_count: int = 0


class RecalledMemory(BaseModel):
    """Một bộ nhớ dài hạn được kéo lên *tự động*, không do model gọi tool.

    Phân biệt với kết quả của tool `extract_memory`: cái đó là model chủ
    động đi tìm, nên nó đã biết mình tìm gì. Cái này đến mà model không xin,
    nên `category` và `score` được render kèm — model cần đủ dữ kiện để tự
    quyết định bỏ qua một dòng không khớp hoàn cảnh người dùng vừa nêu.
    """
    content: str
    category: str
    score: float = 0.0


class ActiveProcedure(BaseModel):
    """Quy trình khớp với hoàn cảnh người dùng vừa nêu, kèm tiến độ hôm nay.

    Khác `RecalledMemory` ở đúng một điểm, và đó là cả lý do nó tồn tại:
    bộ nhớ trả lời "quy trình của bạn là gì", cái này trả lời "bạn còn bước
    nào chưa làm". Câu thứ hai mới là câu người dùng thật sự hỏi khi họ nói
    lại hoàn cảnh.
    """
    procedure_id: str
    title: str
    trigger_text: str
    score: float = 0.0
    pending: list[dict] = Field(default_factory=list, description="Bước chưa xong")
    done: list[dict] = Field(default_factory=list, description="Bước đã xong")
    run_id: str = ""


class InterventionLevels(BaseModel):
    """Mức can thiệp hiệu dụng cho từng loại đề xuất, với **người này**.

    Cùng thang, cùng dữ liệu mà Attention Gate dùng cho kênh thông báo —
    catalog mức nền, cộng vòng học hạ bậc theo số lần người dùng đã bỏ qua,
    cộng công tắc tắt hẳn theo loại. Trước khối này, agent trong chat quyết
    định "nên hỏi hay nên làm" bằng 644 từ prompt và không biết gì về những
    lần người dùng vừa bỏ qua ở bề mặt kia.
    """
    levels: dict[str, str] = Field(default_factory=dict)
    guidance: dict[str, str] = Field(default_factory=dict)


class UnifiedContext(BaseModel):
    """
    Everything Cortex knows about "what the user is doing right now".

    `pills`/`page`/`runtime` mirror the frontend's existing context dict
    verbatim (already injected into the per-message text by
    `_inject_context_into_text` — NOT re-rendered by `to_llm_string()` below,
    to avoid duplicating the same information twice in the prompt).
    `project`/`recent_notes`/`recent_schedules` are new: DB-sourced,
    proactively surfaced without the LLM needing to call a search tool first.
    """
    pills: list[ContextPill] = Field(default_factory=list)
    page: dict[str, Any] = Field(default_factory=dict)
    runtime: dict[str, Any] = Field(default_factory=dict)

    project: Optional[ProjectContext] = None
    recent_notes: list[dict] = Field(default_factory=list, description="Recently edited notes")
    recent_schedules: list[dict] = Field(default_factory=list, description="Upcoming schedules (next 7 days)")
    recalled_memories: list[RecalledMemory] = Field(
        default_factory=list,
        description="Long-term memories matching this turn's message",
    )
    active_procedure: Optional[ActiveProcedure] = None
    intervention: Optional[InterventionLevels] = None

    def to_llm_string(self, max_items: int = 5) -> str:
        """
        Render only the DB-sourced sections (project/recent_notes/
        recent_schedules) for the system prompt. pills/page/runtime are
        deliberately excluded — they're already in the user message via
        _inject_context_into_text; rendering them again here would waste
        tokens on duplicate content instead of reducing them.
        """
        parts = []

        if self.project:
            parts.append(f"Dự án đang mở: {self.project.project_name}")

        if self.recent_notes:
            notes_text = "\n".join(f"- {n.get('title', 'Untitled')}" for n in self.recent_notes[:max_items])
            parts.append(f"Recently edited notes:\n{notes_text}")

        if self.recent_schedules:
            sched_text = "\n".join(
                f"- {s.get('title', 'Untitled')} at {s.get('start_time', '?')}"
                for s in self.recent_schedules[:max_items]
            )
            parts.append(f"Upcoming schedule (next 7 days):\n{sched_text}")

        if self.intervention and self.intervention.levels:
            parts.append(self._render_intervention())

        if self.active_procedure:
            parts.append(self._render_procedure())

        if self.recalled_memories:
            parts.append(self._render_memories(max_items))

        if not parts:
            return ""

        return "User context:\n" + "\n\n".join(parts)

    def _render_intervention(self) -> str:
        """Giọng nào cho từng loại đề xuất, với riêng người dùng này.

        Đây là bản dịch của thang `SILENT < INFORM < RECOMMEND < ASK < ACT`
        sang hành vi hội thoại. Nó thay cho một đoạn prompt tĩnh dài, và
        khác đoạn đó ở chỗ quan trọng nhất: nó **theo người**. Ai bỏ qua
        một loại nhắc nhiều lần sẽ thấy agent tự bớt sốt sắng đúng loại đó,
        chứ không phải nghe cùng một giọng như mọi người khác.

        **Khối này chỉ an toàn khi prompt gọi nó là trần.** Đo được: cùng
        đúng bảng mức này, với một prompt chỉ liệt kê mà không nói nó là
        giới hạn trên, ba kịch bản eval quay ra tệ hơn hẳn — agent tạo task
        người dùng không nhờ, tạo note không ai xin, và đặt lịch 19h bất
        chấp ràng buộc "không họp sau 18h" mà nó vừa đọc thấy. Thêm vào
        prompt câu "It is not advice — it is the upper bound… never raises
        it" thì hai trong ba xanh lại ngay, không đổi một dòng dữ liệu nào.

        Lý do đủ đơn giản để dễ tái phạm: một danh sách "được phép tới mức
        ACT / ASK / RECOMMEND" đọc như *giấy phép*, không như *hạn mức*.
        Ai sửa hàm này về sau, giữ nguyên phần dặn ở cuối, và giữ nguyên
        đoạn "The intervention block is your ceiling" trong
        `assistant_system.md` — hai thứ đó là một cặp, tách ra thì khối
        này thành lời mời hành động.
        """
        lines = [
            "Mức can thiệp cho người dùng này (tính từ hành vi của chính họ, "
            "không phải quy tắc chung):"
        ]
        for reason, level in self.intervention.levels.items():
            how = self.intervention.guidance.get(level, "")
            lines.append(f"- {reason} → {level.upper()}: {how}")
        lines.append(
            "Mức đã hạ nghĩa là người dùng từng nhiều lần bỏ qua loại đó. "
            "Tôn trọng nó — đừng đề xuất hăng hơn mức cho phép, và đừng hỏi "
            "khi mức chỉ là INFORM."
        )
        return "\n".join(lines)

    def _render_procedure(self) -> str:
        """Quy trình đang chạy — và quan trọng nhất, **còn bước nào**.

        Các bước đã xong vẫn được liệt kê, không bị lược đi. Nếu chỉ đưa
        phần còn lại, agent không phân biệt được "quy trình chỉ có hai
        bước" với "quy trình bốn bước, đã xong hai" — và nó sẽ chúc mừng
        người dùng hoàn thành một danh sách mà họ mới làm được một nửa.
        """
        p = self.active_procedure
        # `procedure_id` phải có mặt: `mark_procedure_step` cần nó, và khối
        # này là nơi duy nhất agent nhìn thấy id đó. Thiếu nó thì agent
        # đọc được tiến độ nhưng không cách nào cập nhật.
        lines = [
            f'Quy trình khớp hoàn cảnh vừa nêu: "{p.title}" '
            f"(procedure_id: {p.procedure_id})"
        ]

        if p.done:
            done_text = ", ".join(s.get("title", "?") for s in p.done)
            lines.append(f"Đã xong hôm nay: {done_text}")

        if p.pending:
            lines.append("Còn lại:")
            for step in p.pending:
                hint = step.get("due_hint")
                suffix = f" ({hint})" if hint else ""
                lines.append(f"  {step.get('order')}. {step.get('title')}{suffix}")
        else:
            lines.append("Tất cả các bước đã xong.")

        lines.append(
            "Mọi bước trong \"Còn lại\" đều CHƯA làm — kể cả bước có mốc giờ "
            "đã trôi qua. Quá giờ nghĩa là trễ, không phải xong."
        )
        lines.append(
            "Nói cho người dùng biết còn bước nào, đừng đọc lại từ đầu những "
            "bước họ đã báo xong. Chỉ khi họ BÁO vừa làm xong một bước thì "
            "mới gọi `mark_procedure_step` — copy nguyên văn chuỗi "
            "procedure_id ở trên, kèm số thứ tự bước và câu họ vừa nói. "
            "Vẫn hỏi trước khi tạo việc hay đặt lịch."
        )
        return "\n".join(lines)

    def _render_memories(self, max_items: int) -> str:
        """Bộ nhớ dài hạn, kèm chỉ dẫn cách đọc chúng.

        Ba dòng chỉ dẫn ở cuối không phải trang trí. Khối này xuất hiện ở
        **mọi** lượt, kể cả khi người dùng không hỏi gì liên quan; điểm
        tương đồng ~0.58 không tách được một quy trình đúng khỏi một quy
        trình chỉ tình cờ gần nghĩa (xem phần đo trong
        `semantic_memory_provider.MIN_RELEVANCE_SCORE`). Không có chỉ dẫn,
        kiểu hỏng là agent đọc thấy một quy trình rồi tạo luôn năm task —
        tốn của người dùng một vòng hoàn tác cho thứ họ không hề nhắc tới.
        """
        lines = "\n".join(
            f"- [{m.category}] {m.content}" for m in self.recalled_memories[:max_items]
        )
        return (
            "What you already know about this user (long-term memory, "
            "retrieved automatically — the user did NOT just say these):\n"
            f"{lines}\n"
            "How to use this section:\n"
            "- Check the trigger before trusting a match: does its \"when …\" "
            "clause actually describe what the user just said? If not, ignore "
            "the line — it was matched by similarity, not by meaning.\n"
            "- Use it to avoid asking for what you already know here.\n"
            "- Never create, modify or delete anything from this section alone. "
            "Propose the steps and let the user confirm."
        )
