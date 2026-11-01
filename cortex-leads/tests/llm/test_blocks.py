"""WP32: the two blocks every sandbox that reads a long text or wants JSON from a model builds on."""
import json
from uuid import uuid4

import pytest
from pydantic import BaseModel

from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.db import models as m
from cortex_leads.llm.ask import AskFailed, ask_json
from cortex_leads.llm.gateway import LLMGateway
from cortex_leads.llm.pieces import halve, read_in_pieces, split_text
from cortex_leads.llm.providers import FakeProvider
from cortex_leads.llm.types import LLMResult, LLMTransientError


class Out(BaseModel):
    summary: str


def setup(*answers):
    items = [a if isinstance(a, BaseException) else LLMResult(content=a if isinstance(a, str) else json.dumps(a, ensure_ascii=False),
                                                              tokens_in=10, tokens_out=5, model="fake") for a in answers]
    provider = FakeProvider(items)
    tid = uuid4()
    ctx = RunContext(run_id=uuid4(), tenant_id=tid, sandbox_id=uuid4(), profile="p", profile_version=1,
                     principal=SystemPrincipal(job="t"), scope=Scope())
    run = m.TriggerRun(tenant_id=tid, tokens_in=0, tokens_out=0, status="ok", blocked_codes=[])
    return LLMGateway(provider, retry_delay_s=0), provider, ctx, run


ASK = {"shape": {"summary": "<s>"}, "timeout_s": 5}


async def test_a_good_answer_comes_back_and_its_tokens_are_counted():
    gw, provider, ctx, run = setup({"summary": "ok"})
    assert await ask_json(gw, ctx, run, "sys", "user", **ASK) == {"summary": "ok"}
    assert (run.tokens_in, run.tokens_out) == (10, 5)
    assert provider.calls[0]["messages"][1]["content"].rstrip().endswith("}")  # the closing line draws the shape


async def test_broken_json_is_asked_again_and_both_asks_are_counted():
    gw, provider, ctx, run = setup('{"summary": "chưa đóng', {"summary": "ok"})
    assert await ask_json(gw, ctx, run, "sys", "user", **ASK) == {"summary": "ok"}
    assert run.tokens_in == 20 and "không đúng hình dạng" in provider.calls[1]["messages"][1]["content"]


async def test_the_wrong_keys_are_asked_again_when_a_model_is_given():
    gw, _, ctx, run = setup({"tom_tat": "x"}, {"summary": "ok"})
    got = await ask_json(gw, ctx, run, "sys", "user", model=Out, **ASK)
    assert got == Out(summary="ok")


async def test_giving_up_says_why_as_a_code_and_marks_the_run():
    gw, _, ctx, run = setup("hỏng", "hỏng")
    with pytest.raises(AskFailed) as e:
        await ask_json(gw, ctx, run, "sys", "user", **ASK)
    assert e.value.code == "BAD_SHAPE" and run.status == "blocked" and run.blocked_codes == ["BAD_SHAPE"]


async def test_a_dead_gateway_is_llm_error_not_a_crash():
    gw, _, ctx, run = setup(*[LLMTransientError("down")] * 6)
    with pytest.raises(AskFailed) as e:
        await ask_json(gw, ctx, run, "sys", "user", tries=2, **ASK)
    assert e.value.code == "LLM_ERROR" and run.status == "error"


TEXT = " ".join(f"Câu số {i} nói về một điều gì đó khá dài để đủ nặng." for i in range(120))  # ~6.500 characters
READ = {"system": "s", "prompt": lambda i, n, p: f"{i}/{n}\n{p}", "shape": {"notes": ["<n>"]}, "note": None, "timeout_s": 5, "tries": 2}


def test_pieces_end_at_sentence_ends_and_lose_nothing():
    pieces = split_text(TEXT, 1000)
    assert len(pieces) > 5 and all(p.rstrip().endswith(".") for p in pieces)
    assert " ".join(p.strip() for p in pieces) == TEXT


async def test_every_piece_is_read_in_order_and_saved():
    n = len(split_text(TEXT, 2000))
    gw, provider, ctx, run = setup(*[{"notes": [f"ý {i}"]} for i in range(n)])
    saved: dict = {}
    notes = await read_in_pieces(gw, ctx, run, TEXT, chunk_chars=2000, saved=saved, **READ)
    assert notes == [f"ý {i}" for i in range(n)] and len(saved) == n and len(provider.calls) == n


async def test_a_piece_the_model_cannot_answer_is_cut_in_half():
    gw, provider, ctx, run = setup("hỏng", "hỏng", {"notes": ["nửa đầu"]}, {"notes": ["nửa sau"]})
    saved: dict = {}
    notes = await read_in_pieces(gw, ctx, run, TEXT, chunk_chars=100_000, saved=saved, **READ)
    assert notes == ["nửa đầu", "nửa sau"] and len(provider.calls) == 4
    assert len(saved) == 3  # the two halves and the whole


async def test_a_piece_already_saved_is_not_asked_again():
    pieces = split_text(TEXT, 2000)
    from cortex_leads.llm.pieces import key_of
    gw, provider, ctx, run = setup({"notes": ["mới"]})
    saved = {key_of(p): [f"cũ {i}"] for i, p in enumerate(pieces[:-1])}  # all but the last were done before
    notes = await read_in_pieces(gw, ctx, run, TEXT, chunk_chars=2000, saved=saved, **READ)
    assert notes == [*(f"cũ {i}" for i in range(len(pieces) - 1)), "mới"] and len(provider.calls) == 1


async def test_a_failure_keeps_what_was_read_before_it():
    pieces = split_text(TEXT, 2000)
    gw, _, ctx, run = setup({"notes": ["một"]}, "hỏng", "hỏng", "hỏng", "hỏng")
    saved: dict = {}
    with pytest.raises(AskFailed):
        await read_in_pieces(gw, ctx, run, TEXT, chunk_chars=2000, saved=saved, **READ)
    assert next(iter(saved.values())) == ["một"] and len(pieces) > 1


def test_halving_cuts_near_the_middle_at_a_sentence_end_and_keeps_every_word():
    a, b = halve(TEXT)
    assert abs(len(a) - len(b)) < 200 and a.endswith(".") and f"{a} {b}" == TEXT
    assert halve("một câu duy nhất không có chỗ cắt") == ["một câu duy nhất không có chỗ cắt"]
