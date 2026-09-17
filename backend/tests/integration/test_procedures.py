"""ProcedureService — quy trình có cấu trúc và có trạng thái.

Đây là thứ trả lời được câu mà bộ nhớ dạng câu văn không trả lời được:
"hôm nay tôi còn bước nào chưa làm". Nên phần lớn test ở đây xoay quanh
**trạng thái**, không quanh việc lưu trữ.

Có chạm embedding thật (dịch vụ nội bộ): khớp trigger là điểm khác biệt
chính so với cách cũ, và một test khớp trigger bằng embedding giả sẽ không
kiểm gì cả.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models import ProcedureRunStatus, ProcedureSource
from app.services.procedures import (
    MIN_TRIGGER_SCORE,
    STEP_DONE,
    STEP_SKIPPED,
    ProcedureService,
)

pytestmark = pytest.mark.asyncio

REMOTE_STEPS = [
    {"title": "Daily", "due_hint": "trước 9h sáng"},
    {"title": "Check-in trên web"},
    {"title": "Sync với team", "due_hint": "4h chiều"},
]


@pytest_asyncio.fixture
async def proc_db():
    """Session + tài khoản cô lập, bảng procedures trắng."""
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(
            text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)}
        )
        await db.commit()
        yield db, uid
        await db.rollback()
        await db.execute(
            text("DELETE FROM procedures WHERE user_id = :u"), {"u": str(uid)}
        )
        await db.commit()
    await engine.dispose()


@pytest_asyncio.fixture
async def remote_procedure(proc_db):
    db, uid = proc_db
    service = ProcedureService(db)
    procedure = await service.create(
        user_id=uid,
        title="Quy trình remote",
        trigger_text="khi tôi remote",
        steps=REMOTE_STEPS,
    )
    await db.commit()
    return service, procedure, uid


class TestDefinition:
    async def test_steps_are_numbered_and_cleaned(self, remote_procedure):
        _, procedure, _ = remote_procedure
        assert [s["order"] for s in procedure.steps] == [1, 2, 3]
        assert procedure.steps[0]["due_hint"] == "trước 9h sáng"
        assert procedure.steps[1]["due_hint"] is None

    async def test_a_procedure_without_steps_is_rejected(self, proc_db):
        """Quy trình không bước không trả lời được câu hỏi nó sinh ra để trả lời."""
        db, uid = proc_db
        with pytest.raises(ValueError):
            await ProcedureService(db).create(
                user_id=uid, title="Rỗng", trigger_text="khi gì đó", steps=[]
            )

    async def test_trigger_is_embedded_separately_from_steps(self, remote_procedure):
        """Điểm khác biệt cốt lõi so với bộ nhớ dạng câu văn.

        Embedding dùng để khớp phải là của riêng vế điều kiện. Nếu nó là
        embedding của cả quy trình thì bảng này không sửa được vấn đề xếp
        hạng mà nó sinh ra để sửa.
        """
        from sqlalchemy import select

        from app.models import ProcedureTriggerPhrase

        service, procedure, _ = remote_procedure
        rows = (
            await service.db.execute(
                select(ProcedureTriggerPhrase).where(
                    ProcedureTriggerPhrase.procedure_id == procedure.id
                )
            )
        ).scalars().all()

        assert rows, "không có cách nói nào được lưu"
        assert all(r.embedding is not None for r in rows)
        assert all("Daily" not in r.phrase for r in rows)
        assert procedure.trigger_text == "khi tôi remote"

    async def test_each_trigger_phrase_gets_its_own_row(self, proc_db):
        """Gộp các cách nói vào một embedding làm điểm khớp giảm, không tăng.

        Đo được: trigger "khi tôi làm việc từ xa, remote" khớp "hôm nay tôi
        remote" ở 0.7341; nhồi thành "remote, làm việc từ xa, làm ở nhà,
        wfh" thì tụt xuống 0.6741 và trượt ngưỡng. Nên mỗi cách nói phải là
        một hàng, một embedding.
        """
        from sqlalchemy import select

        from app.models import ProcedureTriggerPhrase

        db, uid = proc_db
        service = ProcedureService(db)
        procedure = await service.create(
            user_id=uid,
            title="Quy trình remote",
            trigger_text="remote, làm việc từ xa, wfh",
            steps=REMOTE_STEPS,
        )
        rows = (
            await db.execute(
                select(ProcedureTriggerPhrase).where(
                    ProcedureTriggerPhrase.procedure_id == procedure.id
                )
            )
        ).scalars().all()
        assert sorted(r.phrase for r in rows) == ["làm việc từ xa", "remote", "wfh"]

    async def test_any_phrase_can_match(self, proc_db):
        """Cách nói thứ ba cũng phải khớp được như cách nói thứ nhất."""
        db, uid = proc_db
        service = ProcedureService(db)
        await service.create(
            user_id=uid,
            title="Quy trình remote",
            trigger_text="remote, làm việc từ xa, wfh",
            steps=REMOTE_STEPS,
        )
        await db.commit()

        for phrasing in ("hôm nay tôi remote", "tuần này tôi wfh"):
            result = await service.match(uid, phrasing)
            assert result is not None, f"không khớp: {phrasing!r}"


class TestTriggerMatching:
    async def test_matches_the_situation_it_describes(self, remote_procedure):
        service, procedure, uid = remote_procedure
        result = await service.match(uid, "hôm nay tôi remote")
        assert result is not None
        matched, score = result
        assert matched.id == procedure.id
        assert score >= MIN_TRIGGER_SCORE

    async def test_does_not_match_an_unrelated_situation(self, remote_procedure):
        """Ngưỡng ở đây chặt hơn bộ nhớ ngữ nghĩa, và đây là lý do.

        Khớp nhầm không chỉ làm nhiễu ngữ cảnh — nó mở một run và đọc cho
        người dùng danh sách việc của một hoàn cảnh khác.
        """
        service, _, uid = remote_procedure
        assert await service.match(uid, "giá bitcoin hôm nay bao nhiêu") is None
        assert await service.match(uid, "deadline dự án sắp tới rồi") is None

    async def test_empty_message_matches_nothing(self, remote_procedure):
        service, _, uid = remote_procedure
        assert await service.match(uid, "") is None

    async def test_match_is_scoped_to_the_owner(self, remote_procedure):
        from uuid import uuid4

        service, _, _ = remote_procedure
        assert await service.match(uuid4(), "hôm nay tôi remote") is None


class TestRunState:
    async def test_opening_a_run_starts_every_step_pending(self, remote_procedure):
        service, procedure, _ = remote_procedure
        run = await service.get_or_open_run(procedure)
        assert run.status == ProcedureRunStatus.ACTIVE
        assert len(service.pending_steps(procedure, run)) == 3

    async def test_saying_the_situation_again_keeps_progress(self, remote_procedure):
        """Bài test trung tâm của cả tính năng.

        "Hôm nay tôi remote" nói lần thứ hai phải trả về đúng run đang
        chạy. Mở một run mới ở đây sẽ xoá sạch những bước người dùng vừa
        báo là đã xong và đọc lại cả danh sách từ đầu — đúng hành vi mà
        người dùng mô tả là "hệ thống không nhớ gì cả".
        """
        service, procedure, _ = remote_procedure
        first = await service.get_or_open_run(procedure)
        await service.mark_step(first, 1, STEP_DONE)

        second = await service.get_or_open_run(procedure)
        assert second.id == first.id
        remaining = [s["title"] for s in service.pending_steps(procedure, second)]
        assert remaining == ["Check-in trên web", "Sync với team"]

    async def test_a_run_conflict_does_not_destroy_the_callers_work(self, remote_procedure):
        """Xung đột khi mở run không được cuốn theo việc của người gọi.

        Service này chạy trên session của agent, giữa lượt chat. Nếu nó xử
        lý xung đột bằng `db.rollback()` thì mọi thứ người gọi đã ghi trong
        cùng session — tin nhắn vừa lưu, task vừa tạo — biến mất theo, vì
        một chuyện nhỏ và cục bộ. Savepoint là thứ giữ phạm vi đúng.
        """
        from sqlalchemy import select, text

        from app.models import Procedure

        service, procedure, uid = remote_procedure

        # Việc "của người gọi" trong cùng session, chưa commit.
        other = Procedure(
            user_id=uid, title="Việc của người gọi",
            trigger_text="không liên quan", steps=[{"order": 1, "title": "x"}],
        )
        service.db.add(other)
        await service.db.flush()

        # Một run active đã tồn tại (giả lập request đến trước) — được ghi
        # qua một kết nối khác để nó thật sự nằm ngoài session này.
        from app.database_async import make_async_sessionmaker

        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as other_db:
            await other_db.execute(
                text(
                    "INSERT INTO procedure_runs (procedure_id, user_id, status, step_states) "
                    "VALUES (:p, :u, 'active', '[]'::jsonb)"
                ),
                {"p": str(procedure.id), "u": str(uid)},
            )
            await other_db.commit()
        await engine.dispose()

        run = await service.get_or_open_run(procedure)
        assert run is not None

        # Việc của người gọi vẫn còn trong session sau khi xung đột được xử lý.
        still_there = (
            await service.db.execute(
                select(Procedure).where(Procedure.title == "Việc của người gọi")
            )
        ).scalar_one_or_none()
        assert still_there is not None, "xung đột đã cuốn theo việc của người gọi"

    async def test_completing_every_step_closes_the_run(self, remote_procedure):
        service, procedure, _ = remote_procedure
        run = await service.get_or_open_run(procedure)
        for order in (1, 2, 3):
            await service.mark_step(run, order, STEP_DONE)

        assert run.status == ProcedureRunStatus.COMPLETED
        assert run.completed_at is not None
        assert service.pending_steps(procedure, run) == []

    async def test_a_skipped_step_is_not_still_pending(self, remote_procedure):
        """Bỏ qua khác chưa làm — hỏi lại một bước đã cố ý bỏ là phiền."""
        service, procedure, _ = remote_procedure
        run = await service.get_or_open_run(procedure)
        await service.mark_step(run, 2, STEP_SKIPPED)
        assert [s["order"] for s in service.pending_steps(procedure, run)] == [1, 3]

    async def test_marking_a_step_that_does_not_exist_is_an_error(self, remote_procedure):
        service, procedure, _ = remote_procedure
        run = await service.get_or_open_run(procedure)
        with pytest.raises(ValueError):
            await service.mark_step(run, 99, STEP_DONE)

    async def test_step_state_survives_a_reload(self, remote_procedure):
        """JSONB phải thật sự được ghi xuống, không chỉ đổi trong bộ nhớ.

        SQLAlchemy so sánh cột JSON bằng identity, nên sửa danh sách tại
        chỗ mà không `flag_modified` sẽ không sinh UPDATE nào — và tiến độ
        biến mất ở request kế tiếp mà không có lỗi nào.
        """
        from app.database_async import make_async_sessionmaker

        service, procedure, _ = remote_procedure
        run = await service.get_or_open_run(procedure)
        await service.mark_step(run, 1, STEP_DONE)
        await service.db.commit()

        # Session **mới**, không phải `expire_all()` trên session cũ: đây
        # là điều request kế tiếp thật sự làm, và nó đọc từ DB chứ không từ
        # identity map — thứ duy nhất chứng minh được UPDATE đã xảy ra.
        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as fresh_db:
            reloaded = await ProcedureService(fresh_db).get_active_run(procedure.id)
            done = [s for s in reloaded.step_states if s["status"] == STEP_DONE]
        await engine.dispose()

        assert len(done) == 1
        assert done[0]["order"] == 1


class TestInProgressTakesPriority:
    """Đang ở giữa một quy trình là một **trạng thái**, không phải một câu nói.

    Lỗi đo được khi khối quy trình còn phụ thuộc vào việc lượt nói có khớp
    trigger hay không: người dùng gõ "daily xong rồi nhé" — không có từ nào
    khớp trigger "remote" — nên khối biến mất, agent mất `procedure_id`, và
    nó bịa ra một id (`remote_work_2026-09-10`) khiến lời gọi tool hỏng.
    """

    async def test_current_run_is_found_without_mentioning_the_trigger(
        self, remote_procedure
    ):
        service, procedure, uid = remote_procedure
        await service.get_or_open_run(procedure)
        await service.db.commit()

        found = await service.current_run_for_user(uid)
        assert found is not None
        assert found[0].id == procedure.id

    async def test_no_run_means_nothing_is_in_progress(self, remote_procedure):
        service, _, uid = remote_procedure
        assert await service.current_run_for_user(uid) is None

    async def test_a_stale_run_is_abandoned_not_resumed(self, remote_procedure):
        """Quy trình bỏ dở hôm kia không được đeo theo mãi.

        Khối tiến độ giờ hiện ở mọi lượt khi có run đang mở, nên không có
        hạn thì một lần bỏ dở sẽ bám vào mọi cuộc trò chuyện về sau — và
        tệ hơn, nó chặn mất run mới khi người dùng bước vào cùng hoàn cảnh
        hôm nay (bất biến một-run-active từ chối cái thứ hai).
        """
        from datetime import datetime, timedelta

        from app.models import ProcedureRunStatus
        from app.services.procedures import RUN_STALE_AFTER_HOURS

        service, procedure, uid = remote_procedure
        run = await service.get_or_open_run(procedure)
        run.started_at = datetime.utcnow() - timedelta(hours=RUN_STALE_AFTER_HOURS + 1)
        await service.db.flush()

        assert await service.current_run_for_user(uid) is None
        assert await service.get_current_run(procedure.id) is None
        assert run.status == ProcedureRunStatus.ABANDONED

        # Và người dùng bước vào lại hoàn cảnh đó hôm nay thì mở được run mới.
        fresh = await service.get_or_open_run(procedure)
        assert fresh.id != run.id
        assert fresh.status == ProcedureRunStatus.ACTIVE
