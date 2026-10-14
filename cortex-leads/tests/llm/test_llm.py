import asyncio
import time
from uuid import uuid4

import pytest

from cortex_leads.core.context import RunContext, Scope, SystemPrincipal
from cortex_leads.llm import FakeProvider, LLMGateway, LLMResult, parse_json_object, response_shape
from cortex_leads.llm.providers import classify_error
from cortex_leads.llm.types import (
    LLMFatalError,
    LLMQuotaError,
    LLMTimeoutError,
    LLMTransientError,
    ScriptExhaustedError,
    ShapeError,
)


def make_ctx(tenant=None) -> RunContext:
    return RunContext(run_id=uuid4(), tenant_id=tenant or uuid4(), sandbox_id=uuid4(),
                      profile="p", profile_version=1, principal=SystemPrincipal("t"), scope=Scope())


OK = LLMResult(content="hi", tokens_in=3, tokens_out=2, model="m")


def gw(script, **kw):
    kw.setdefault("retry_delay_s", 0.001)
    p = FakeProvider(script)
    return p, LLMGateway(p, **kw)


async def test_returns_result_and_counts_tokens():
    ctx = make_ctx()
    _, g = gw([OK, OK])
    await g.complete(ctx, [])
    await g.complete(ctx, [])
    assert g.usage[ctx.tenant_id] == (6, 4)


async def test_retries_transient_then_succeeds():
    p, g = gw([LLMTransientError("x"), LLMTransientError("y"), OK])
    assert (await g.complete(make_ctx(), [])).content == "hi"
    assert len(p.calls) == 3


async def test_transient_exhausts_attempts():
    p, g = gw([LLMTransientError("x")] * 5, max_attempts=3)
    with pytest.raises(LLMTransientError):
        await g.complete(make_ctx(), [])
    assert len(p.calls) == 3


@pytest.mark.parametrize("err", [LLMFatalError("401"), LLMQuotaError("429")])
async def test_no_retry_for_fatal_or_quota(err):
    p, g = gw([err, OK])
    with pytest.raises(type(err)):
        await g.complete(make_ctx(), [])
    assert len(p.calls) == 1


class _Status(Exception):
    def __init__(self, code):
        self.status_code = code


@pytest.mark.parametrize("code,kind", [(429, LLMQuotaError), (401, LLMFatalError),
                                       (404, LLMFatalError), (503, LLMTransientError),
                                       (502, LLMTransientError)])
def test_classify_by_status_code(code, kind):
    assert isinstance(classify_error(_Status(code)), kind)


async def test_raw_status_error_retried_only_when_5xx():
    p, g = gw([_Status(503), OK])
    await g.complete(make_ctx(), [])
    assert len(p.calls) == 2
    p, g = gw([_Status(429), OK])
    with pytest.raises(LLMQuotaError):
        await g.complete(make_ctx(), [])
    assert len(p.calls) == 1


async def test_timeout_raises_and_retries():
    async def slow(messages, tools):
        await asyncio.sleep(1)
        return OK

    p, g = gw([slow, slow], max_attempts=2)
    with pytest.raises(LLMTimeoutError):
        await g.complete(make_ctx(), [], timeout_s=0.02)
    assert len(p.calls) == 2


def tracker(delay=0.03):
    state = {"cur": 0, "peak": 0}

    async def call(messages, tools):
        state["cur"] += 1
        state["peak"] = max(state["peak"], state["cur"])
        await asyncio.sleep(delay)
        state["cur"] -= 1
        return OK

    return state, call


async def test_per_tenant_concurrency_limit():
    state, call = tracker()
    _, g = gw([call] * 6, global_concurrency=10, per_tenant_concurrency=2)
    ctx = make_ctx()
    await asyncio.gather(*(g.complete(ctx, []) for _ in range(6)))
    assert state["peak"] == 2


async def test_global_limit_and_tenants_do_not_block_each_other():
    state, call = tracker()
    _, g = gw([call] * 6, global_concurrency=3, per_tenant_concurrency=2)
    ctxs = [make_ctx() for _ in range(3)]
    await asyncio.gather(*(g.complete(c, []) for c in ctxs for _ in range(2)))
    assert state["peak"] == 3

    # a saturated tenant must not delay another tenant
    state, call = tracker(0.1)
    _, g = gw([call] * 5, global_concurrency=4, per_tenant_concurrency=1)
    noisy, quiet = make_ctx(), make_ctx()
    tasks = [asyncio.create_task(g.complete(noisy, [])) for _ in range(4)]
    await asyncio.sleep(0.01)
    t0 = time.monotonic()
    await g.complete(quiet, [])
    assert time.monotonic() - t0 < 0.25
    await asyncio.gather(*tasks)


async def test_fake_provider_exhausted_is_clear():
    _, g = gw([OK])
    await g.complete(make_ctx(), [])
    with pytest.raises(ScriptExhaustedError, match="exhausted"):
        await g.complete(make_ctx(), [])


async def test_fake_provider_callable_sees_messages_and_tools():
    seen = {}

    def fn(messages, tools):
        seen["m"], seen["t"] = messages, tools
        return LLMResult(content="x")

    _, g = gw([fn])
    await g.complete(make_ctx(), [{"role": "user", "content": "q"}], tools=[{"a": 1}])
    assert seen == {"m": [{"role": "user", "content": "q"}], "t": [{"a": 1}]}


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": {"b": [1, 2]}}\n```', {"a": {"b": [1, 2]}}),
    ('```\n{"a": 1}\n```', {"a": 1}),
    ('Đây là kết quả:\n{"act": "none"}\nHy vọng hữu ích.', {"act": "none"}),
    ('Xong. ```json\n{"x": "} {"}\n``` hết', {"x": "} {"}),
    ('lead [1] then {"k": 2}', {"k": 2}),
])
def test_parse_json_object_ok(text, expected):
    assert parse_json_object(text) == expected


@pytest.mark.parametrize("text,match", [
    ("", "empty"), (None, "empty"), ("không có json", "no JSON object"),
    ("[1, 2]", "array|list"), ('"abc"', "no JSON object"), ('{"a": 1,', "no JSON object"),
])
def test_parse_json_object_errors(text, match):
    with pytest.raises(ShapeError, match=match):
        parse_json_object(text)


def test_response_shape_draws_example():
    out = response_shape({"act": "draft", "claims": [{"value": "2.500.000đ", "source_id": "id"}]})
    assert '"claims": [' in out and '"source_id"' in out
    assert out.splitlines()[-1] == "}"


def test_parse_json_object_ignores_a_reasoning_block() -> None:
    text = '<think>maybe {"act": "draft", "text": "giá 9.000.000đ"}? no.</think>\n{"act": "none"}'
    assert parse_json_object(text) == {"act": "none"}
    with pytest.raises(ShapeError):  # cut off mid-thought: nothing was answered
        parse_json_object('<think>trying {"act": "draft"}')
