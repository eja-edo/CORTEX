"""ProcedureService — quy trình của người dùng, và trạng thái từng lần chạy.

Trả lời được câu mà bộ nhớ dạng câu văn không trả lời được: *"hôm nay tôi
còn bước nào chưa làm?"*

Hai quyết định định hình cả file:

**Khớp trên trigger, không trên toàn văn.** `Procedure.trigger_embedding`
chỉ embed vế điều kiện ("khi tôi remote"), không kèm bước nào. Lý do đo
được: khi cả quy trình được embed làm một, đoạn dài lấn át vế điều kiện —
quy trình remote xếp hạng nhất ở 8/9 truy vấn trong phép đo 2026-09-10, kể
cả "giá bitcoin bao nhiêu".

**Một quy trình có tối đa một run đang chạy**, và bất biến đó do DB ép
(`uq_procedure_runs_one_active`). Service ở đây không giả định mình là
người ghi duy nhất: `get_or_open_run` bắt xung đột và đọc lại, vì hai
request gần nhau là chuyện thường ở một bot chat.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.embedding_service import get_embedding_service
from app.models import (
    Procedure,
    ProcedureRun,
    ProcedureRunStatus,
    ProcedureSource,
    ProcedureTriggerPhrase,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Ngưỡng khớp trigger, trên thang cosine.
#
# Cao hơn hẳn `MIN_RELEVANCE_SCORE` (0.55) của bộ nhớ ngữ nghĩa, vì hai đại
# lượng khác nhau: ở đây hai vế được so đều là *hoàn cảnh* ("wfh" vs "tuần
# này tôi wfh"), không phải một câu hỏi so với một đoạn văn dài. Tín hiệu
# sạch hơn nhiều nên phổ điểm giãn ra, và có chỗ để chặt tay.
#
# Đo 2026-09-10, 3 quy trình, 8 truy vấn, mỗi cách nói của trigger là một
# hàng riêng (`ProcedureTriggerPhrase`):
#
#     cuối tháng rồi                → Chốt sổ cuối tháng       0.9387  ✓
#     chiều nay có demo cho khách   → Chuẩn bị demo            0.8483  ✓
#     tuần này tôi wfh              → Quy trình remote         0.8076  ✓
#     mai tôi làm ở nhà             → Quy trình remote         0.7683  ✓
#     hôm nay tôi remote            → Quy trình remote         0.7006  ✓
#     ────────────────────────────────── ngưỡng 0.70 ──────────────────
#     deadline dự án sắp tới rồi    → (cao nhất)               0.6870  ✓ không khớp
#     giá bitcoin bao nhiêu         → (cao nhất)               0.5567  ✓ không khớp
#     thời tiết hôm nay thế nào     → (cao nhất)               0.5473  ✓ không khớp
#
# 8/8. Ba thiết kế đã thử, cùng bộ truy vấn:
#
#     trigger gộp một chuỗi, ít biến thể     5/7
#     trigger gộp một chuỗi, nhiều biến thể  6/8   ← thêm biến thể làm TỆ đi
#     mỗi biến thể một hàng, lấy max         8/8
#
# Biên giữa khớp thấp nhất (0.7006) và nhiễu cao nhất (0.6870) chỉ 0.0136 —
# hẹp, nên coi 0.70 là con số đã hiệu chuẩn theo dữ liệu thật chứ không
# phải một hằng số tròn trịa chọn bừa. Đổi mô hình embedding thì phải đo
# lại; `tests/integration/test_procedures.py` là chỗ phát hiện ra.
#
# Chặt tay là đúng ở đây vì hậu quả hai phía không cân nhau: khớp hụt thì
# agent trả lời như bình thường, và bộ nhớ ngữ nghĩa vẫn đưa cùng routine
# đó vào ngữ cảnh ở ngưỡng lỏng hơn của nó — hai đường bổ sung nhau, đường
# này chỉ thêm khả năng mở run và đọc tiến độ. Khớp nhầm thì agent mở một
# run và đọc cho người dùng danh sách việc của một hoàn cảnh khác.
MIN_TRIGGER_SCORE = 0.70

# Một run bỏ dở bao lâu thì thôi không coi là "đang làm" nữa.
#
# Cần một giới hạn, vì khối tiến độ giờ xuất hiện ở **mọi** lượt khi có run
# đang mở — không còn phụ thuộc trigger. Không có nó, một quy trình người
# dùng bỏ giữa chừng hôm thứ Hai sẽ đeo theo mọi cuộc trò chuyện mãi mãi.
#
# 24 giờ, không phải "cùng ngày dương lịch": người làm khuya báo xong một
# bước lúc 00:30 vẫn đang ở trong cùng một buổi làm việc, và một mốc nửa
# đêm sẽ cắt đúng vào giữa nó.
RUN_STALE_AFTER_HOURS = 24

STEP_PENDING = "pending"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"


def _normalise_steps(steps: list[dict] | None) -> list[dict]:
    """Đánh số lại 1..n và chỉ giữ các khoá đã biết.

    Thứ tự là thứ người dùng nghe khi hỏi "còn bước nào", nên nó phải là
    một dãy liên tục, không phải thứ model tình cờ sinh ra.
    """
    out: list[dict] = []
    for raw in steps or []:
        if not isinstance(raw, dict):
            continue
        title = (raw.get("title") or "").strip()
        if not title:
            continue
        # Đánh số theo `out`, không theo vị trí trong input: một mục bị bỏ
        # (rỗng, hoặc không phải dict) sẽ tạo lỗ hổng trong dãy nếu đếm
        # theo input — quy trình khi đó có "bước 1" và "bước 3", và
        # `mark_step(2)` báo lỗi cho một bước người dùng nhìn thấy.
        out.append({
            "order": len(out) + 1,
            "title": title,
            "due_hint": (raw.get("due_hint") or "").strip() or None,
        })
    return out


def split_trigger(trigger_text: str) -> list[str]:
    """Tách "remote, làm việc từ xa, wfh" thành từng cách nói.

    Mỗi cách nói được embed riêng — gộp lại làm điểm khớp giảm chứ không
    tăng, xem docstring của `ProcedureTriggerPhrase`.
    """
    seen: set[str] = set()
    phrases = []
    for raw in (trigger_text or "").split(","):
        phrase = raw.strip()
        key = phrase.lower()
        if phrase and key not in seen:
            seen.add(key)
            phrases.append(phrase)
    return phrases


def _initial_states(steps: list[dict]) -> list[dict]:
    return [
        {"order": s["order"], "status": STEP_PENDING, "completed_at": None}
        for s in steps
    ]


class ProcedureService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self._embeddings = get_embedding_service()

    # ── Định nghĩa quy trình ───────────────────────────────────────────

    async def create(
        self,
        *,
        user_id: UUID,
        title: str,
        trigger_text: str,
        steps: list[dict],
        source: ProcedureSource = ProcedureSource.USER_STATED,
        confidence: float = 0.9,
        source_memory_id: UUID | None = None,
    ) -> Procedure:
        clean_steps = _normalise_steps(steps)
        if not clean_steps:
            raise ValueError("Một quy trình không có bước nào thì không dùng được")

        phrases = split_trigger(trigger_text)
        if not phrases:
            raise ValueError("Quy trình phải có ít nhất một cách nói cho trigger")

        procedure = Procedure(
            user_id=user_id,
            title=title.strip(),
            trigger_text=trigger_text.strip(),
            steps=clean_steps,
            source=source,
            confidence=confidence,
            source_memory_id=source_memory_id,
        )
        self.db.add(procedure)
        await self.db.flush()

        await self._embed_phrases(procedure, phrases)

        logger.info(
            "Procedure created: %s (%d bước, %d cách nói trigger)",
            procedure.id, len(clean_steps), len(phrases),
        )
        return procedure

    async def _embed_phrases(self, procedure: Procedure, phrases: list[str]) -> None:
        """Sinh embedding cho từng cách nói, một lô một lời gọi."""
        embeddings = await self._embeddings.embed_batch(phrases)
        for phrase, embedding in zip(phrases, embeddings):
            if embedding is None:
                # Không chặn việc ghi: quy trình vẫn hiện ở danh sách và
                # vẫn dùng được bằng tay. Chỉ cách nói này mất khả năng tự
                # khớp — mất một tính năng còn hơn mất cả bản ghi.
                logger.warning(
                    "Không sinh được embedding cho cách nói %r", phrase[:40]
                )
            self.db.add(
                ProcedureTriggerPhrase(
                    procedure_id=procedure.id, phrase=phrase, embedding=embedding
                )
            )
        await self.db.flush()

    async def replace_trigger(self, procedure: Procedure, trigger_text: str) -> None:
        """Thay toàn bộ cách nói của một quy trình."""
        from sqlalchemy import delete

        phrases = split_trigger(trigger_text)
        if not phrases:
            return
        await self.db.execute(
            delete(ProcedureTriggerPhrase).where(
                ProcedureTriggerPhrase.procedure_id == procedure.id
            )
        )
        procedure.trigger_text = trigger_text.strip()
        await self._embed_phrases(procedure, phrases)

    async def list_active(self, user_id: UUID) -> list[Procedure]:
        stmt = (
            select(Procedure)
            .where(Procedure.user_id == user_id, Procedure.is_active.is_(True))
            .order_by(Procedure.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    # ── Khớp trigger ───────────────────────────────────────────────────

    async def match(
        self, user_id: UUID, message: str, min_score: float = MIN_TRIGGER_SCORE
    ) -> tuple[Procedure, float] | None:
        """Quy trình có trigger khớp lượt nói này, nếu có.

        Trả về **một** kết quả, không phải danh sách: một lượt nói mô tả
        một hoàn cảnh. Đưa ra ba quy trình rồi để agent chọn chỉ chuyển
        chỗ đoán từ đây sang đó, và ở đây có điểm số để quyết.
        """
        if not message or not message.strip():
            return None

        query_embedding = await self._embeddings.embed_query(message)
        if query_embedding is None:
            return None

        embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        # `<=>` — toán tử cosine, khớp với `vector_cosine_ops` của
        # `ix_procedures_trigger_hnsw`. Dùng toán tử khác opclass thì
        # planner bỏ qua index, đúng lỗi `semantic_memories` từng mang.
        # Điểm của một quy trình = điểm **cao nhất** trong các cách nói của
        # nó. `ORDER BY score DESC LIMIT 1` trên bảng cách nói cho đúng kết
        # quả đó mà không cần GROUP BY, và giữ được index HNSW.
        stmt = text("""
            SELECT t.procedure_id,
                   (1 - (t.embedding <=> CAST(:q AS vector))) AS score
            FROM procedure_trigger_phrases t
            JOIN procedures p ON p.id = t.procedure_id
            WHERE p.user_id = :user_id
              AND p.is_active IS TRUE
              AND t.embedding IS NOT NULL
            ORDER BY score DESC
            LIMIT 1
        """)
        row = (
            await self.db.execute(
                stmt, {"q": embedding_str, "user_id": str(user_id)}
            )
        ).one_or_none()

        if row is None or float(row[1]) < min_score:
            return None

        procedure = await self.db.get(Procedure, row[0])
        if procedure is None:
            return None
        return procedure, float(row[1])

    # ── Lần chạy ───────────────────────────────────────────────────────

    async def get_active_run(self, procedure_id: UUID) -> ProcedureRun | None:
        stmt = select(ProcedureRun).where(
            ProcedureRun.procedure_id == procedure_id,
            ProcedureRun.status == ProcedureRunStatus.ACTIVE,
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_current_run(self, procedure_id: UUID) -> ProcedureRun | None:
        """Run đang mở **và còn hạn**; run quá hạn được đóng lại tại đây.

        Khác `get_active_run` (đọc thô): hàm này là thứ tầng trên nên dùng,
        vì nó cũng dọn. Một run bỏ dở từ hôm kia không phải "đang làm" —
        trả nó về sẽ khiến agent hỏi tiếp một danh sách đã cũ, và tệ hơn,
        chặn mất run mới khi người dùng bước vào cùng hoàn cảnh hôm nay
        (bất biến một-run-active sẽ từ chối cái thứ hai).
        """
        run = await self.get_active_run(procedure_id)
        if run is None:
            return None

        cutoff = datetime.utcnow() - timedelta(hours=RUN_STALE_AFTER_HOURS)
        if run.started_at and run.started_at < cutoff:
            run.status = ProcedureRunStatus.ABANDONED
            await self.db.flush()
            logger.info(
                "Procedure run %s quá %dh — đánh dấu bỏ dở",
                run.id, RUN_STALE_AFTER_HOURS,
            )
            return None

        return run

    async def current_run_for_user(
        self, user_id: UUID
    ) -> tuple[Procedure, ProcedureRun] | None:
        """Quy trình người dùng **đang ở giữa**, nếu có.

        Đây là nhánh ưu tiên của việc dựng ngữ cảnh, và nó tồn tại vì một
        lỗi đo được: người dùng nói "daily xong rồi nhé" — câu đó không
        chứa từ nào khớp trigger "remote", nên khối quy trình không hiện,
        nên agent không có `procedure_id` để gọi tool, nên nó **bịa ra
        một id** ("remote_work_2026-09-10") và lời gọi thất bại.

        Đang ở giữa một quy trình là một trạng thái, không phải một câu
        nói. Khi trạng thái đó tồn tại, nó thuộc về ngữ cảnh bất kể lượt
        này người dùng gõ gì.
        """
        stmt = (
            select(ProcedureRun)
            .where(
                ProcedureRun.user_id == user_id,
                ProcedureRun.status == ProcedureRunStatus.ACTIVE,
            )
            .order_by(ProcedureRun.started_at.desc())
            .limit(1)
        )
        run = (await self.db.execute(stmt)).scalar_one_or_none()
        if run is None:
            return None

        cutoff = datetime.utcnow() - timedelta(hours=RUN_STALE_AFTER_HOURS)
        if run.started_at and run.started_at < cutoff:
            run.status = ProcedureRunStatus.ABANDONED
            await self.db.flush()
            return None

        procedure = await self.db.get(Procedure, run.procedure_id)
        if procedure is None or not procedure.is_active:
            return None
        return procedure, run

    async def get_or_open_run(self, procedure: Procedure) -> ProcedureRun:
        """Run đang chạy, hoặc mở một run mới.

        Đây là chỗ "nhắc lại hoàn cảnh lần thứ hai" phải giữ được tiến độ:
        trả lại đúng run cũ chứ không mở danh sách trắng đè lên những bước
        người dùng vừa báo là xong.
        """
        existing = await self.get_current_run(procedure.id)
        if existing is not None:
            return existing

        # Savepoint, **không** phải transaction của session.
        #
        # Service này chạy trên session của agent (ContextService gọi nó
        # giữa lượt chat), nên một `db.rollback()` ở đây sẽ cuốn theo mọi
        # thứ người gọi đã ghi trong cùng session — tin nhắn vừa lưu, task
        # vừa tạo. Một xung đột khi mở run là chuyện nhỏ và cục bộ; nó
        # không được phép huỷ công việc của người khác.
        #
        # `begin_nested()` phát SAVEPOINT, nên chỉ phần INSERT này bị lùi.
        run = ProcedureRun(
            procedure_id=procedure.id,
            user_id=procedure.user_id,
            status=ProcedureRunStatus.ACTIVE,
            step_states=_initial_states(procedure.steps or []),
        )
        try:
            async with self.db.begin_nested():
                self.db.add(run)
                await self.db.flush()
        except IntegrityError:
            # `uq_procedure_runs_one_active` vừa chặn: một request khác mở
            # run trước ta trong tích tắc. Đó là kết quả đúng, không phải
            # lỗi — lùi lại và dùng run của họ.
            existing = await self.get_active_run(procedure.id)
            if existing is None:
                raise
            logger.info(
                "Đã có request khác mở run cho procedure %s — dùng lại run %s",
                procedure.id, existing.id,
            )
            return existing

        logger.info("Procedure run mở: %s (procedure=%s)", run.id, procedure.id)
        return run

    def pending_steps(self, procedure: Procedure, run: ProcedureRun) -> list[dict]:
        """Các bước chưa xong, theo thứ tự — câu trả lời cho "còn gì phải làm"."""
        done = {
            s["order"]
            for s in (run.step_states or [])
            if s.get("status") in (STEP_DONE, STEP_SKIPPED)
        }
        return [s for s in (procedure.steps or []) if s["order"] not in done]

    async def mark_step(
        self, run: ProcedureRun, order: int, status: str = STEP_DONE
    ) -> ProcedureRun:
        """Đánh dấu một bước, và tự đóng run khi không còn bước nào."""
        if status not in (STEP_PENDING, STEP_DONE, STEP_SKIPPED):
            raise ValueError(f"Trạng thái bước không hợp lệ: {status!r}")

        states = list(run.step_states or [])
        found = False
        for state in states:
            if state.get("order") == order:
                state["status"] = status
                state["completed_at"] = (
                    datetime.utcnow().isoformat() if status != STEP_PENDING else None
                )
                found = True
                break
        if not found:
            raise ValueError(f"Quy trình không có bước số {order}")

        run.step_states = states
        # JSONB được gán lại cả khối chứ không sửa tại chỗ: SQLAlchemy so
        # sánh bằng identity cho kiểu JSON, nên mutate danh sách in-place
        # sẽ không được đánh dấu là bẩn và UPDATE lặng lẽ không xảy ra.
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(run, "step_states")

        if all(s.get("status") in (STEP_DONE, STEP_SKIPPED) for s in states):
            run.status = ProcedureRunStatus.COMPLETED
            run.completed_at = datetime.utcnow()
            logger.info("Procedure run hoàn tất: %s", run.id)

        await self.db.flush()
        return run
