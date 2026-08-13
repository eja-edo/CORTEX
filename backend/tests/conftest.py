"""
Test-session setup, loaded before any test module or application code.

**This file's environment overrides must run first.** pytest imports
`conftest.py` before collecting any test module, which is the one point in
the whole test session early enough to matter here: `app.config.Settings`
reads `os.getenv(...)` once, at import time, and every test file that does
`from app.config import settings` (directly or through anything it imports)
freezes whatever was in the environment at that moment.
"""

import os

# Route every test's Redis traffic to a database index the dev backend never
# touches.
#
# Found the hard way: every `pytest` run was XADD-ing into the exact same
# `events:*` streams the live `python main.py` process reads from — there
# was no test/production separation at all. A handful of test runs pushed
# roughly 25,000 entries into streams the durable consumer replays in full
# on every backend startup, which is what produced the log flood and
# thousands of wasted event-subscriber recomputations for rows that were
# only ever test fixtures.
#
# `Settings.REDIS_URL` prefers an explicit `REDIS_URL` env var (unset here,
# per `.env`) and otherwise builds `redis://HOST:PORT/{REDIS_DB}` — so
# overriding just `REDIS_DB` is enough to redirect every EventBus, snapshot
# store and (for the same reason) semantic-memory Redis connection at once,
# with no test file needing to know this happened.
#
# `load_dotenv()` (called at `app.config` import time) does not override an
# already-set environment variable, so setting these here — before anything
# imports `app.config` — is what makes them stick for the whole session.
os.environ.setdefault("REDIS_DB", "15")
os.environ.setdefault("MEMORY_REDIS_DB", "14")


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Start every test session from an empty test-Redis database.

    Without this, the *test* database index would eventually accumulate the
    same kind of unbounded stream growth this file exists to keep out of the
    real one — just relocated, not solved. `FLUSHDB` only clears whichever
    logical database the connection is currently pointed at (the one just
    selected above), so this can never reach database 0.
    """
    import redis

    from app.config import settings

    try:
        client = redis.from_url(settings.REDIS_URL)
        client.flushdb()
        client.close()
    except Exception as exc:  # pragma: no cover - best-effort hygiene only
        print(f"[conftest] Could not flush test Redis DB (non-fatal): {exc}")
