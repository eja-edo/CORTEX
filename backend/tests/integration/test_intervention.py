"""Mức can thiệp cho hội thoại — cùng thang mà Attention Gate dùng.

Trước khi có nó, agent trong chat quyết định "nên hỏi hay nên làm" bằng 644
từ prompt, không biết gì về những lần người dùng vừa bỏ qua ở kênh thông
báo. Đo được: `app/ai/` không có một dòng nào chạm tới `attention_gate`,
`reason_key` hay `feedback_loop`.

Điều quan trọng nhất các test dưới đây canh: hàm này dùng **cùng dữ liệu**
với Gate (catalog + feedback loop + tắt theo loại), và **bỏ đúng một bước**
của Gate — kiểm tra người dùng có đang bận không.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.models import AttentionLevel
from app.services.attention_reason_catalog import base_level_for
from app.services.intervention import (
    LEVEL_GUIDANCE,
    conversational_level,
    levels_for,
)

pytestmark = pytest.mark.asyncio

REASON = "chat.suggest_support"  # nền RECOMMEND


@pytest_asyncio.fixture
async def clean_user():
    """Tài khoản cô lập, không lịch sử dismiss, không tuỳ chọn nào."""
    from app.database_async import make_async_sessionmaker
    from tests.integration.isolated_user import ensure_isolated_user

    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_isolated_user(db)
        await db.execute(text("DELETE FROM attention_log WHERE user_id = :u"), {"u": str(uid)})
        await db.execute(text("DELETE FROM user_preferences WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
        yield db, uid
        await db.rollback()
        await db.execute(text("DELETE FROM attention_log WHERE user_id = :u"), {"u": str(uid)})
        await db.execute(text("DELETE FROM user_preferences WHERE user_id = :u"), {"u": str(uid)})
        await db.commit()
    await engine.dispose()


async def _add_dismissals(db, uid, reason_key, n):
    """n lần người dùng bỏ qua loại nhắc này."""
    for _ in range(n):
        await db.execute(
            text(
                "INSERT INTO attention_log "
                "(id, user_id, item_type, item_id, reason_key, level, channel, response) "
                "VALUES (uuid_generate_v7(), :u, 'task', uuid_generate_v7(), :r, "
                "'recommend', 'in_app', 'dismissed')"
            ),
            {"u": str(uid), "r": reason_key},
        )
    await db.commit()


class TestSharesTheLadderWithTheGate:
    async def test_fresh_user_gets_the_catalog_baseline(self, clean_user):
        db, uid = clean_user
        assert await conversational_level(db, uid, REASON) == base_level_for(REASON)

    async def test_dismissals_lower_the_level(self, clean_user):
        """Vòng học của kênh thông báo giờ áp cả cho chat.

        Đây là nửa mà người dùng cảm nhận được: bỏ qua một loại nhắc đủ
        nhiều thì agent trong chat cũng thôi sốt sắng, chứ không chỉ kênh
        notification im đi.
        """
        from app.config import settings

        db, uid = clean_user
        before = await conversational_level(db, uid, REASON)
        await _add_dismissals(db, uid, REASON, settings.FEEDBACK_LOOP_DISMISS_THRESHOLD)
        after = await conversational_level(db, uid, REASON)

        ladder = [
            AttentionLevel.SILENT, AttentionLevel.INFORM, AttentionLevel.RECOMMEND,
            AttentionLevel.ASK, AttentionLevel.ACT,
        ]
        assert ladder.index(after) == ladder.index(before) - 1

    async def test_turning_a_reason_off_silences_it(self, clean_user):
        """Tắt hẳn một loại thì tắt ở cả hai bề mặt, không chỉ notification."""
        from app.services.user_preferences import set_reason_enabled_async

        db, uid = clean_user
        await set_reason_enabled_async(db, uid, reason_key=REASON, enabled=False)
        await db.commit()
        assert await conversational_level(db, uid, REASON) == AttentionLevel.SILENT

    async def test_dismissals_of_another_reason_do_not_bleed(self, clean_user):
        """Chán một loại không làm im loại khác."""
        db, uid = clean_user
        await _add_dismissals(db, uid, "task.stale", 20)
        assert await conversational_level(db, uid, REASON) == base_level_for(REASON)

    async def test_dismissals_are_per_user(self, clean_user):
        from uuid import uuid4

        db, uid = clean_user
        await _add_dismissals(db, uid, REASON, 20)
        other = await conversational_level(db, uuid4(), REASON)
        assert other == base_level_for(REASON)


class TestDiffersFromTheGateOnPurpose:
    async def test_quiet_hours_do_not_silence_a_conversation(self, clean_user):
        """Bước duy nhất của Gate mà hàm này cố ý bỏ.

        Thông báo là *đẩy* — nó chen vào giờ của người dùng nên phải hỏi họ
        có bận không. Hội thoại là *kéo*: họ vừa gõ một câu. Ai mở chat lúc
        11 giờ đêm là đang chọn nói chuyện lúc 11 giờ đêm, và im lặng vì
        "ngoài giờ" là trả lời sai câu họ vừa hỏi.
        """
        from datetime import time

        from app.services.user_preferences import upsert_quiet_hours_async

        db, uid = clean_user
        # Quiet hours phủ trọn ngày — nếu bước busy được áp, mọi lượt sẽ im.
        await upsert_quiet_hours_async(
            db, uid, quiet_hours_start=time(0, 0), quiet_hours_end=time(23, 59)
        )
        await db.commit()

        assert await conversational_level(db, uid, REASON) == base_level_for(REASON)


class TestNeverBreaksTheTurn:
    async def test_an_unknown_reason_falls_back_not_raises(self, clean_user):
        """Reason lạ rơi về mặc định của catalog (INFORM), không ném lỗi."""
        db, uid = clean_user
        level = await conversational_level(db, uid, "chat.reason_chưa_khai")
        assert isinstance(level, AttentionLevel)

    async def test_a_broken_session_falls_back_to_the_baseline(self, clean_user, monkeypatch):
        """Mức can thiệp chỉ tinh chỉnh giọng — hỏng thì không được giết lượt chat."""
        db, uid = clean_user

        async def boom(*args, **kwargs):
            raise RuntimeError("DB sập")

        monkeypatch.setattr(
            "app.services.intervention.dismiss_count_async", boom
        )
        assert await conversational_level(db, uid, REASON) == base_level_for(REASON)


class TestGuidance:
    def test_every_level_has_guidance(self):
        """Một mức không có hướng dẫn thì agent không biết dịch nó ra giọng nào."""
        for level in AttentionLevel:
            assert level in LEVEL_GUIDANCE, f"thiếu hướng dẫn cho {level}"

    async def test_levels_for_returns_one_entry_per_key(self, clean_user):
        db, uid = clean_user
        keys = ["chat.suggest_support", "chat.flag_conflict"]
        got = await levels_for(db, uid, keys)
        assert set(got) == set(keys)


class TestReachesTheSystemPrompt:
    """Mức tính ra rồi mà không tới được prompt thì không đổi được gì."""

    async def test_levels_are_rendered_for_the_model(self, clean_user):
        from app.context.context_service import ContextService

        db, uid = clean_user
        ctx = await ContextService(db).build_context(user_id=uid, message="chào bạn")
        rendered = ctx.to_llm_string()

        assert "Mức can thiệp cho người dùng này" in rendered
        assert "chat.suggest_routine_tasks" in rendered

    async def test_a_downgraded_level_shows_up_downgraded(self, clean_user):
        """Đường đi trọn vẹn: người dùng bỏ qua → mức hạ → prompt đổi.

        Đây là thứ khiến hành vi chat trở nên **theo người**. Không có mắt
        xích cuối này, vòng học vẫn chạy nhưng agent không bao giờ biết.
        """
        from app.config import settings
        from app.context.context_service import ContextService

        db, uid = clean_user
        reason = "chat.suggest_support"  # nền RECOMMEND

        before = (await ContextService(db).build_context(user_id=uid, message="x"))
        assert before.intervention.levels[reason] == "recommend"

        await _add_dismissals(db, uid, reason, settings.FEEDBACK_LOOP_DISMISS_THRESHOLD)

        after = (await ContextService(db).build_context(user_id=uid, message="x"))
        assert after.intervention.levels[reason] == "inform"
        assert "INFORM" in after.to_llm_string()

    async def test_guidance_only_covers_levels_actually_present(self, clean_user):
        """Không tiêu prompt budget cho những mức lượt này không dùng tới."""
        from app.context.context_service import ContextService

        db, uid = clean_user
        ctx = await ContextService(db).build_context(user_id=uid, message="x")
        used = set(ctx.intervention.levels.values())
        assert set(ctx.intervention.guidance) == used

    async def test_context_survives_a_broken_intervention_lookup(self, clean_user, monkeypatch):
        """Khối này hỏng thì agent hành xử như trước, không mất lượt chat."""
        from app.context.context_service import ContextService

        db, uid = clean_user

        async def boom(*args, **kwargs):
            raise RuntimeError("sập")

        monkeypatch.setattr("app.services.intervention.levels_for", boom)
        ctx = await ContextService(db).build_context(user_id=uid, message="x")
        assert ctx.intervention is None
        assert isinstance(ctx.to_llm_string(), str)


class TestPromptStatesTheCeiling:
    """Prompt phải nói rõ thang là **trần**, không phải gợi ý.

    Hai trục khác nhau và cả hai đều cần: "low/high stakes" đo độ khó hoàn
    tác của *tình huống*, thang can thiệp đo *người dùng này* có muốn nghe
    loại đó không. Thang đặt trần, stakes chọn điểm dưới trần — nếu prompt
    không nói rõ điều đó, model sẽ coi hai thứ là mâu thuẫn và chọn bừa một
    cái.
    """

    def _prompt(self) -> str:
        from pathlib import Path

        return Path("app/ai/prompts/system/assistant_system.md").read_text(
            encoding="utf-8"
        )

    def test_prompt_names_the_block(self):
        assert "Mức can thiệp cho người dùng này" in self._prompt()

    def test_prompt_calls_it_a_ceiling_not_advice(self):
        prompt = self._prompt()
        assert "ceiling" in prompt.lower()
        assert "never raises it" in prompt

    def test_prompt_keeps_the_stakes_judgment(self):
        """Thang không thay thế phán đoán stakes — bỏ nó là mất một trục."""
        prompt = self._prompt()
        assert "Low stakes vs high stakes" in prompt

    def test_prompt_forbids_asking_at_inform(self):
        assert "Do not ask." in self._prompt()
