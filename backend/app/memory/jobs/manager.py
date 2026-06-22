import asyncio
import logging
from typing import Dict, Any
from datetime import datetime
from functools import partial

from redis import Redis
from rq import Queue

logger = logging.getLogger(__name__)


class MemoryJobManager:
    """
    Manages async memory extraction jobs via Redis Queue.
    """

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379,
                 redis_db: int = 1):
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.redis_db = redis_db
        self._redis_conn = None
        self._queue = None

    def _get_queue(self) -> Queue:
        if self._queue is None:
            self._redis_conn = Redis(host=self.redis_host, port=self.redis_port, db=self.redis_db)
            self._queue = Queue("memory_extraction", connection=self._redis_conn)
        return self._queue

    async def enqueue_extraction(self, message_id: str, user_id: str,
                                  conversation_id: str, content: str,
                                  signals: list, priority: str = "low"):
        job_data = {
            "message_id": message_id,
            "user_id": user_id,
            "conversation_id": conversation_id,
            "content": content,
            "signals": signals,
            "enqueued_at": datetime.utcnow().isoformat(),
            "priority": priority,
        }

        loop = asyncio.get_running_loop()
        queue = self._get_queue()

        if priority == "high":
            job = await loop.run_in_executor(
                None,
                partial(queue.enqueue,
                        "app.workers.memory_worker.process_memory_extraction",
                        job_data,
                        job_timeout=300,
                        job_id=f"mem_ext_{message_id}"),
            )
        else:
            job = await loop.run_in_executor(
                None,
                partial(queue.enqueue,
                        "app.workers.memory_worker.process_memory_extraction",
                        job_data,
                        job_timeout=120),
            )

        logger.info("Enqueued extraction job %s (priority=%s)", job.id, priority)
        return job.id
