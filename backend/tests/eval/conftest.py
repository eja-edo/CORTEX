"""Fixtures cho bộ eval sống — mọi test ở đây gọi LLM thật, tốn tiền thật."""

import pytest
import pytest_asyncio

from app.database_async import make_async_sessionmaker
from tests.eval.harness import ensure_eval_user, reset_eval_user, seed_memories


def pytest_collection_modifyitems(config, items):
    """Mọi test trong thư mục này mặc định mang marker `live_llm`.

    Không phải đánh dấu tay từng cái: quên một cái nghĩa là nó lọt vào lần
    chạy `pytest` bình thường của ai đó và âm thầm gọi API tính tiền.
    """
    for item in items:
        if "tests/eval/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.live_llm)


@pytest_asyncio.fixture(autouse=True)
async def _fresh_async_engine():
    """Vứt engine async toàn cục giữa các test.

    `app.database_async._async_engine` là một global khởi tạo **một lần**,
    trên event loop đầu tiên gọi tới nó. pytest-asyncio dựng một loop mới
    cho mỗi test (`asyncio_default_fixture_loop_scope = function`), nên từ
    test thứ hai trở đi, pool của engine vẫn đang giữ những connection
    asyncpg thuộc một loop đã chết.

    Triệu chứng không hề giống nguyên nhân, và đó là lý do fixture này có
    docstring dài: mọi tool chạy qua `_exec_parallel` trả về
    `{"error": "Task ... attached to a different loop"}` — bị bắt và báo
    lại như một lần gọi tool thất bại bình thường. Nên bài eval đỏ với lý
    do "agent không cập nhật được tiến độ", trong khi agent đã gọi đúng
    tool với đúng UUID và chính hạ tầng test mới là thứ hỏng.

    Production không có vấn đề này: backend chạy một event loop duy nhất
    suốt vòng đời tiến trình.
    """
    yield
    from app.database_async import close_async_engine

    await close_async_engine()


@pytest_asyncio.fixture
async def eval_user():
    """Tài khoản trắng cho mỗi test — dựng, xoá sạch, giao lại."""
    engine, session_maker = make_async_sessionmaker()
    async with session_maker() as db:
        uid = await ensure_eval_user(db)
        await reset_eval_user(db)
    await engine.dispose()
    return uid


@pytest_asyncio.fixture
async def memory_seeder(eval_user):
    """Nạp bộ nhớ dài hạn cho tài khoản eval, qua đường ghi thật."""

    async def _seed(memories: list[tuple[str, str]]):
        engine, session_maker = make_async_sessionmaker()
        async with session_maker() as db:
            await seed_memories(db, memories)
        await engine.dispose()

    return _seed
