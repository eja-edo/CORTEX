"""WP27 AI tổng: proposals for the owner, and a chat that only ever sees numbers."""
import pytest
from support import h, sign_in
from wp5_support import gateway, reply, rows

from cortex_leads.console.assistant import FALLBACK, get_gateway
from cortex_leads.db import models as m


async def owner(app_client, world, api_key_factory, role="owner"):
    _, key = await api_key_factory(world.t, role, "nv1" if role == "staff" else None)
    app_client.cookies.clear()
    return await sign_in(app_client, key)


@pytest.fixture
def use_llm(app_client):
    app = app_client._transport.app

    def install(*script):
        gw, prov = gateway(*script)
        app.dependency_overrides[get_gateway] = lambda: gw
        return prov

    yield install
    app.dependency_overrides.clear()


async def digest_box(world, sandbox_factory):
    return await sandbox_factory(world.t, name="owner_digest", purpose="owner_digest", profile_ref="digest_template@1")


async def runs(world, seed, n, **kw):
    for _ in range(n):
        await seed(m.TriggerRun(**{**dict(tenant_id=world.t.id, sandbox_id=world.sb.id, skill_name="tra-loi-khach", skill_version=16,
                                          profile="customer_drafter", profile_version=1, event_type="conversation.awaiting_reply",
                                          status="ok", blocked_codes=[]), **kw}))


def answer(text, refused=False):
    return reply({"reply": text, "refused": refused})


async def test_proposals_are_the_owners_and_accepting_one_acts(app_client, world, api_key_factory, seed):
    p = await seed(m.Proposal(tenant_id=world.t.id, sandbox_id=world.sb.id, kind="pause_sandbox", signal="error_streak",
                              target={"skill": "tra-loi-khach"}, evidence={"consecutive_errors": 3}))
    csrf = await owner(app_client, world, api_key_factory, "staff")
    assert (await app_client.get("/api/v1/proposals")).status_code == 403
    csrf = await owner(app_client, world, api_key_factory)
    (item,) = (await app_client.get("/api/v1/proposals")).json()["items"]
    assert item["signal"] == "lỗi liên tiếp" and item["skill"] == "tra-loi-khach" and item["danger"] is True
    assert item["action"] == "Tạm dừng AI của sandbox này" and item["evidence"] == ["lỗi liên tiếp: 3"]
    assert (await app_client.post(f"/api/v1/proposals/{p.id}/accept", headers=h(csrf))).json() == {"status": "accepted"}
    assert [s.status for s in await rows(world, m.Sandbox)] == ["paused"]
    assert (await app_client.get("/api/v1/proposals")).json()["items"] == []
    assert (await app_client.post(f"/api/v1/proposals/{p.id}/maybe", headers=h(csrf))).status_code == 422


async def test_a_strategy_card_shows_its_one_change(app_client, world, api_key_factory, seed):
    await seed(m.Proposal(tenant_id=world.t.id, sandbox_id=world.sb.id, kind="tune_skill", signal="skipped_high",
                          target={"skill": "hoi-lai-khach-im", "version": 4, "change": {"field": "limits.max_touches", "from": 3, "to": 2}},
                          evidence={"decided": 5, "skipped": 4}))
    await owner(app_client, world, api_key_factory)
    (item,) = (await app_client.get("/api/v1/proposals")).json()["items"]
    assert item["change"] == {"field": "limits.max_touches", "from": 3, "to": 2} and item["kind"] == "tune_skill" and item["danger"] is False


async def test_chat_needs_the_owner_and_the_digest_sandbox(app_client, world, api_key_factory, use_llm):
    use_llm(answer("Có 3 lượt chạy."))
    csrf = await owner(app_client, world, api_key_factory, "staff")
    body = {"messages": [{"role": "user", "content": "Tuần này thế nào?"}]}
    assert (await app_client.post("/api/v1/assistant/chat", json=body, headers=h(csrf))).status_code == 403
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json=body, headers=h(csrf))
    assert r.status_code == 409 and r.json()["detail"]["code"] == "NO_DIGEST_SANDBOX"


async def test_the_model_is_given_numbers_and_never_a_word_a_customer_wrote(app_client, world, api_key_factory, use_llm, sandbox_factory, seed):
    await digest_box(world, sandbox_factory)
    await runs(world, seed, 6, status="blocked", blocked_codes=["UNVERIFIED_CLAIM"])
    await runs(world, seed, 4)
    prov = use_llm(answer("Kỹ năng tra-loi-khach có 10 lượt chạy, 6 lượt bị chặn (60%), mã chặn nhiều nhất là UNVERIFIED_CLAIM."))
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "Kỹ năng nào bị chặn nhiều nhất?"}]},
                              headers=h(csrf))
    assert r.status_code == 200 and r.json()["verified"] is True and "60%" in r.json()["reply"] and r.json()["refused"] is False
    sent = "\n".join(x["content"] for x in prov.calls[0]["messages"])
    assert '"luot_chay": 10' in sent and '"ti_le_chan_pct": 60' in sent and "UNVERIFIED_CLAIM" in sent
    for secret in ("Nguyễn Văn An", "0901", "Khóa IELTS", "Chào shop"):  # the world's customer and what they wrote
        assert secret not in sent
    (run,) = [x for x in await rows(world, m.TriggerRun) if x.skill_name == "tro-chuyen-ai-tong"]
    assert (run.status, run.event_type) == ("ok", "console.chat") and run.tokens_in > 0


async def test_a_number_the_model_made_up_is_replaced_by_an_honest_answer(app_client, world, api_key_factory, use_llm, sandbox_factory, seed):
    await digest_box(world, sandbox_factory)
    await runs(world, seed, 6)
    use_llm(answer("Tuần này tăng 250% so với tuần trước, rất tốt."))
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "Tuần này thế nào?"}]}, headers=h(csrf))
    assert r.status_code == 200 and r.json() == {"reply": FALLBACK, "refused": False, "verified": False}
    (run,) = [x for x in await rows(world, m.TriggerRun) if x.skill_name == "tro-chuyen-ai-tong"]
    assert (run.status, run.blocked_codes) == ("blocked", ["UNVERIFIED_CLAIM"])


async def test_a_number_the_owner_typed_may_be_echoed_back(app_client, world, api_key_factory, use_llm, sandbox_factory):
    await digest_box(world, sandbox_factory)
    use_llm(answer("Trong 30 ngày thì mình chưa có số liệu, chỉ có 7 ngày gần nhất."))
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "Cho mình số liệu 30 ngày"}]}, headers=h(csrf))
    assert r.json()["verified"] is True and "30 ngày" in r.json()["reply"]


async def test_asking_for_a_customers_words_is_refused_and_pointed_at_the_inbox(app_client, world, api_key_factory, use_llm, sandbox_factory):
    await digest_box(world, sandbox_factory)
    use_llm(answer("Mình không đọc được nội dung tin nhắn của khách, bạn mở Hộp thư để xem nhé.", refused=True))
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "Khách Nguyễn Văn An đã nói gì?"}]},
                              headers=h(csrf))
    assert r.json()["refused"] is True and "Hộp thư" in r.json()["reply"]


async def test_bad_requests_and_a_dead_model(app_client, world, api_key_factory, use_llm, sandbox_factory):
    from cortex_leads.llm.types import LLMFatalError
    await digest_box(world, sandbox_factory)
    use_llm(LLMFatalError("down"))
    csrf = await owner(app_client, world, api_key_factory)
    ask = lambda msgs: app_client.post("/api/v1/assistant/chat", json={"messages": msgs}, headers=h(csrf))
    assert (await ask([{"role": "assistant", "content": "xin chào"}])).status_code == 422
    assert (await ask([])).status_code == 422 and (await ask([{"role": "user", "content": "x" * 601}])).status_code == 422
    r = await ask([{"role": "user", "content": "Tuần này thế nào?"}])
    assert r.status_code == 503 and r.json()["detail"]["code"] == "LLM_UNAVAILABLE"
    assert [x.status for x in await rows(world, m.TriggerRun) if x.skill_name == "tro-chuyen-ai-tong"] == ["error"]


async def test_the_chat_budget_is_the_digest_sandboxs_and_a_paused_one_refuses(app_client, world, api_key_factory, use_llm, sandbox_factory):
    box = await digest_box(world, sandbox_factory)
    use_llm(answer("Có 0 lượt chạy."))
    from sqlalchemy import update

    from cortex_leads.db.session import tenant_session
    async with tenant_session(world.t.id) as s:
        await s.execute(update(m.Sandbox).where(m.Sandbox.id == box.id).values(status="paused"))
    csrf = await owner(app_client, world, api_key_factory)
    r = await app_client.post("/api/v1/assistant/chat", json={"messages": [{"role": "user", "content": "Tuần này thế nào?"}]}, headers=h(csrf))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "PAUSED"  # the kill switch covers the supervisor too
