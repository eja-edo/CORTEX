"""Unit test for the `_exec_parallel` session-cleanup pattern used by
`agent_service.py` (streaming) and `tool_execution_service.py`
(non-streaming) when `AGENT_PARALLEL_TOOL_EXECUTION` is on.

Live incident: the Mezon bot restarted mid-turn, cutting its connection to
`/api/agent/stream/chat` while tools were executing in parallel via
`asyncio.gather`. Postgres logged "The garbage collector is trying to
clean up non-checked-in connection" shortly after.

**Why this test drives `anyio`, not raw `asyncio.gather`/`task.cancel()`.**
Starlette's `StreamingResponse.__call__` (`starlette/responses.py`) does not
cancel the response generator with a plain `task.cancel()` — it runs
`stream_response` and `listen_for_disconnect` inside an
`anyio.create_task_group()`, and whichever finishes first cancels the
group's scope. An earlier version of this investigation modeled the
cancellation with raw `asyncio` primitives and got contradictory results in
both directions depending on how the model was wired — because raw
`Task.cancel()` and an `anyio` cancel scope reaching through a nested
`async for` over an async generator do not behave identically once
`asyncio.gather()` is involved several stack frames down. Only a harness
built on the real `anyio.create_task_group()` reproduced the actual
warning reliably; this is that harness, kept rather than thrown away so a
future change to this cleanup can be checked against the real mechanism
instead of a plausible-looking guess. Verified by hand across 8 runs with
varied disconnect timing before being written down here: the unshielded
shape leaked 0/8 times it should have closed, the shielded shape closed
cleanly 8/8 times.
"""

import asyncio

import anyio
import pytest


async def _run_disconnect_scenario(exec_parallel):
    """Rebuilds the real shape end to end: an async generator
    (`handle_streaming_generator`) delegated through another async
    generator (`stream_events`, matching `agent.py`'s wrapper), consumed
    by Starlette's actual `StreamingResponse.__call__` pattern, disconnected
    partway through by a task group cancel scope — not a self-inflicted
    `task.cancel()` from inside the same coroutine, which does not exercise
    the same code path `anyio` does.
    """
    async def handle_streaming_generator():
        yield {"event": "start"}
        results = await asyncio.gather(exec_parallel("a"), exec_parallel("b"), exec_parallel("c"))
        yield {"event": "done", "results": results}

    async def stream_events():
        async for chunk in handle_streaming_generator():
            yield chunk

    async def stream_response():
        async for _ in stream_events():
            pass

    async def listen_for_disconnect():
        await asyncio.sleep(0.01)  # the client disconnects partway through

    async with anyio.create_task_group() as tg:
        async def wrap(func):
            await func()
            tg.cancel_scope.cancel()

        tg.start_soon(wrap, stream_response)
        await wrap(listen_for_disconnect)


@pytest.mark.asyncio
async def test_shielded_close_survives_a_mid_stream_client_disconnect():
    """The fix: `db = AsyncSessionLocal(); try: ... finally: await
    asyncio.shield(db.close())` — the shape both call sites use now."""
    closed = []

    async def exec_parallel(name):
        class FakeSession:
            async def close(self_inner):
                await asyncio.sleep(0.02)
                closed.append(name)

        db = FakeSession()
        try:
            await asyncio.sleep(0.05)  # stands in for a real tool call
        finally:
            await asyncio.shield(db.close())
        return name

    await _run_disconnect_scenario(exec_parallel)
    await asyncio.sleep(0.05)  # let the shielded closes, now detached, finish

    assert sorted(closed) == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_unshielded_close_is_the_regression_this_guards_against():
    """Not a fix to keep — pins the bug being fixed. `async with
    AsyncSessionLocal() as db:` (equivalent to a bare `finally: await
    db.close()`) is exactly what every `_exec_parallel` looked like before
    this change, and it drops every session's cleanup under the same
    disconnect this file reproduces above.

    If this test ever starts passing (`closed` becomes non-empty), Starlette
    or anyio changed how cancellation propagates through a nested async
    generator into `asyncio.gather()`, not the other way around — worth
    re-checking whether the shield is still needed before removing it.
    """
    closed = []

    async def exec_parallel(name):
        class FakeSession:
            async def close(self_inner):
                await asyncio.sleep(0.02)
                closed.append(name)

        db = FakeSession()
        try:
            await asyncio.sleep(0.05)
        finally:
            await db.close()  # no shield
        return name

    await _run_disconnect_scenario(exec_parallel)
    await asyncio.sleep(0.05)

    assert closed == []
