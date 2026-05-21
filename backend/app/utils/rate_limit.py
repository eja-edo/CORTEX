from collections import defaultdict, deque
from threading import Lock
from time import time
from uuid import UUID


class InMemorySlidingWindowRateLimiter:
    """Simple per-user in-memory sliding-window limiter.

    Note: in-memory limiter is process-local. For multi-instance deployments,
    replace this with a Redis-backed limiter.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, user_id: UUID, route_key: str) -> tuple[bool, int]:
        key = f"{user_id}:{route_key}"
        now = time()
        cutoff = now - self.window_seconds

        with self._lock:
            bucket = self._buckets[key]
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.limit:
                retry_after = int(max(1, self.window_seconds - (now - bucket[0])))
                return False, retry_after

            bucket.append(now)
            return True, 0
