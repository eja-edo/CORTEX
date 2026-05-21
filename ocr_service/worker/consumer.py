"""
OCR Consumer - Redis Stream Consumer

Consumes OCR tasks from Redis stream and processes them.
Updated to use standardized RedisStreamService.
"""

import asyncio
import logging
from typing import Optional

from config import settings
from worker.processor import OCRTaskProcessor
from lib.redis_stream_service import RedisStreamService
from worker.ocr_processor_task import OCRProcessorTask, OCR_PROCESSOR_STREAM_KEY, OCR_CONSUMER_GROUP

logger = logging.getLogger(__name__)


class OCRConsumer:
    """
    Redis stream consumer for OCR tasks using standardized service.
    
    Features:
    - Connection pooling
    - Worker heartbeat
    - Task recovery (orphaned tasks)
    - Graceful shutdown
    """
    
    def __init__(self):
        self._redis_service: Optional[RedisStreamService] = None
        self._processor = OCRTaskProcessor()
        self._running = False

    async def start(self) -> None:
        """Start consuming tasks from Redis stream."""
        # Initialize standardized Redis stream service
        self._redis_service = RedisStreamService.get_instance(
            task_class=OCRProcessorTask,
            stream_key=OCR_PROCESSOR_STREAM_KEY,
            group_name=OCR_CONSUMER_GROUP,
        )
        
        await self._redis_service.connect()
        await self._redis_service.start_background_tasks()
        
        self._running = True
        logger.info(f"OCR Consumer started | group={OCR_CONSUMER_GROUP} (standardized)")
        await self._consume_loop()

    async def stop(self) -> None:
        """Stop consuming and close Redis connection."""
        self._running = False
        
        if self._redis_service:
            # Stop background tasks (heartbeat, recovery)
            await self._redis_service.stop_background_tasks()
            # Disconnect and release pending tasks
            await self._redis_service.disconnect(release_pending=True)
            self._redis_service = None
        
        logger.info("OCR Consumer stopped")

    async def _consume_loop(self) -> None:
        """Main consumer loop using standardized service."""
        while self._running:
            try:
                # Read tasks from stream (blocks for 5 seconds if no tasks)
                tasks = await self._redis_service.read_tasks(count=1, block_ms=5000)
                
                if not tasks:
                    continue
                
                for task in tasks:
                    try:
                        logger.info(f"🔍 Processing OCR task: {task.task_id} (video={task.video_path})")
                        await self._processor.process(task)
                        
                        # Acknowledge successful completion
                        await self._redis_service.acknowledge(task)
                        logger.info(f"✅ OCR task completed: {task.task_id}")
                        
                    except Exception as e:
                        logger.exception(f"❌ OCR task {task.task_id} failed: {e}")
                        
                        # Reject task (will retry up to max_retries, then move to DLQ)
                        try:
                            await self._redis_service.reject(
                                task,
                                error=str(e)[:500],  # Truncate long errors
                                retry=True
                            )
                        except Exception as reject_error:
                            logger.error(f"Failed to reject task {task.task_id}: {reject_error}")
            
            except Exception as e:
                logger.error(f"Consumer loop error: {e}", exc_info=True)
                await asyncio.sleep(5)
