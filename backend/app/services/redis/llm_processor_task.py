"""
LLM Processor Task — Redis Stream Task Definition

Represents a task for LLM (Gemini) processing of OCR frames.
Standardized to support both ProducerTaskProtocol and StreamTaskProtocol.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, ClassVar, Optional, Dict

from app.services.redis.stream_base import BaseProducerTask
from app.services.redis.redis_producer_service import create_producer_service

LLM_PROCESSOR_STREAM_KEY = "llm:processor:stream"
LLM_CONSUMER_GROUP = "llm-processor-workers"


@dataclass
class LLMProcessorTask(BaseProducerTask):
    """
    Task definition for LLM processing.
    
    Extends BaseProducerTask for producing and implements StreamTaskProtocol
    for consuming (via from_stream_message classmethod).
    """

    asset_id: str = ""
    user_id: str = ""
    ocr_job_id: str = ""
    job_context: Optional[dict[str, Any]] = None
    
    # For consumer side (StreamTaskProtocol) - not set by producer
    message_id: str = ""

    def to_dict(self) -> dict[str, str]:
        base_dict = super().to_dict()
        base_dict.update({
            "asset_id": self.asset_id,
            "user_id": self.user_id,
            "ocr_job_id": self.ocr_job_id,
            "job_context": json.dumps(self.job_context or {}),
        })
        return base_dict
    
    @classmethod
    def from_stream_message(cls, message_id: str, data: Dict[bytes, bytes]) -> 'LLMProcessorTask':
        """
        Create task instance from Redis stream message.
        
        Required by StreamTaskProtocol for consumer compatibility.
        """
        def decode_bytes(val):
            """Decode bytes to string."""
            if isinstance(val, bytes):
                return val.decode('utf-8')
            return val
        
        def decode_key(key):
            """Decode bytes key to string."""
            if isinstance(key, bytes):
                return key.decode('utf-8')
            return key
        
        # Decode all keys and values
        decoded_data = {decode_key(k): decode_bytes(v) for k, v in data.items()}
        
        # Parse job_context if present
        job_context = None
        if decoded_data.get('job_context'):
            try:
                job_context = json.loads(decoded_data['job_context'])
            except (json.JSONDecodeError, TypeError):
                job_context = {}
        
        # Parse priority
        try:
            priority = int(decoded_data.get('priority', '5'))
        except ValueError:
            priority = 5
        
        # Parse retry count
        try:
            retry_count = int(decoded_data.get('retry_count', '0'))
        except ValueError:
            retry_count = 0
        
        return cls(
            task_id=decoded_data.get('task_id', ''),
            message_id=message_id,
            retry_count=retry_count,
            priority=priority,
            created_at=float(decoded_data.get('created_at', time.time())),
            asset_id=decoded_data.get('asset_id', ''),
            user_id=decoded_data.get('user_id', ''),
            ocr_job_id=decoded_data.get('ocr_job_id', ''),
            job_context=job_context,
        )


class LLMProcessorProducer:
    """
    Producer for LLM processor tasks.
    
    DEPRECATED: Use create_producer_service(LLMProcessorTask, LLM_PROCESSOR_STREAM_KEY) instead.
    Kept for backward compatibility.
    """

    _instance: ClassVar[Optional["LLMProcessorProducer"]] = None

    def __init__(self):
        self._stream_key = LLM_PROCESSOR_STREAM_KEY
        self._producer = None

    async def connect(self) -> None:
        """Connect to Redis via standardized producer service."""
        if self._producer is None:
            self._producer = create_producer_service(LLMProcessorTask, self._stream_key)
            await self._producer.connect()

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._producer:
            await self._producer.close()
            self._producer = None

    async def enqueue(self, task: LLMProcessorTask) -> str:
        """
        Enqueue a task to the LLM processor stream.

        Returns:
            task_id: Unique task identifier
        """
        if self._producer is None:
            await self.connect()

        return await self._producer.enqueue(task)

    @classmethod
    def get_instance(cls) -> "LLMProcessorProducer":
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


async def enqueue_llm_processing(
    asset_id: str,
    user_id: str,
    ocr_job_id: str,
    job_context: Optional[dict] = None,
) -> str:
    """
    Enqueue an LLM processing task.

    Args:
        asset_id: Asset/video ID
        user_id: User ID
        ocr_job_id: OCR job ID from MongoDB
        job_context: Optional context dict

    Returns:
        task_id: Unique task identifier
    """
    producer = LLMProcessorProducer.get_instance()
    task = LLMProcessorTask(
        asset_id=asset_id,
        user_id=user_id,
        ocr_job_id=ocr_job_id,
        job_context=job_context,
    )
    return await producer.enqueue(task)
