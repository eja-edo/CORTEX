"""
Background worker for computing note embeddings asynchronously.

This worker:
1. Listens to Redis Stream "embedding:tasks"
2. Consumes tasks to generate note embeddings
3. Stores embeddings in PostgreSQL
4. Handles failures gracefully
5. Can run independently of the main API

Usage:
    python -m app.worker.embedding_worker

Environment:
    - REDIS_URL: Redis connection string
    - DATABASE_URL: PostgreSQL synchronous connection
    - OPENAI_API_KEY: OpenAI-compatible API key
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Optional
from uuid import UUID

import redis.asyncio as redis
from sqlalchemy import update, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.models import Note
from app.services.agent.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


class EmbeddingWorker:
    """
    Background worker for computing and storing note embeddings.
    
    Processes tasks from Redis Stream and updates PostgreSQL.
    Designed to run as an independent long-lived service.
    """
    
    STREAM_KEY = "embedding:tasks"
    CONSUMER_GROUP = "embedding-workers"
    BATCH_SIZE = 10
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.embedding_service = EmbeddingService()
        self.redis_client: Optional[redis.Redis] = None
        self.async_engine = None
        self.async_session_maker = None
    
    async def initialize(self):
        """Initialize Redis and database connections."""
        self.redis_client = redis.from_url(self.settings.REDIS_URL)
        
        self.async_engine = create_async_engine(
            self.settings.ASYNC_DATABASE_URL,
            echo=False,
            pool_size=5,
            max_overflow=10,
        )
        
        self.async_session_maker = sessionmaker(
            self.async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        
        # Create consumer group (idempotent)
        try:
            await self.redis_client.xgroup_create(self.STREAM_KEY, self.CONSUMER_GROUP, id="0")
            logger.info("embedding_worker_consumer_group_created", extra={"group": self.CONSUMER_GROUP})
        except redis.ResponseError:
            logger.info("embedding_worker_consumer_group_exists", extra={"group": self.CONSUMER_GROUP})
    
    async def shutdown(self):
        """Cleanup connections."""
        if self.redis_client:
            await self.redis_client.close()
        if self.async_engine:
            await self.async_engine.dispose()
    
    async def run(self):
        """Main worker loop."""
        await self.initialize()
        logger.info("embedding_worker_started")
        
        try:
            while True:
                await self.process_batch()
                await asyncio.sleep(1)  # Small delay to avoid busy-waiting
        except KeyboardInterrupt:
            logger.info("embedding_worker_stopping")
        except Exception as e:
            logger.error(f"embedding_worker_error: {e}", exc_info=True)
        finally:
            await self.shutdown()
    
    async def process_batch(self):
        """Process a batch of embedding tasks."""
        try:
            # Read messages from stream
            messages = await self.redis_client.xreadgroup(
                {self.STREAM_KEY: ">"},
                self.CONSUMER_GROUP,
                count=self.BATCH_SIZE,
                block=5000,  # 5 second timeout
            )
            
            if not messages:
                return  # No messages available
            
            # Process each message
            for stream_key, stream_messages in messages:
                for message_id, message_data in stream_messages:
                    await self.process_message(message_id, message_data)
        
        except Exception as e:
            logger.error(f"batch_processing_error: {e}", exc_info=True)
    
    async def process_message(self, message_id: bytes, message_data: dict):
        """
        Process a single embedding task.
        
        Expected message format:
        {
            "note_id": "uuid",
            "content": "note content text",
            "user_id": "uuid"
        }
        """
        try:
            # Decode message
            note_id_str = message_data.get(b"note_id", b"").decode()
            content = message_data.get(b"content", b"").decode()
            user_id_str = message_data.get(b"user_id", b"").decode()
            
            if not note_id_str or not content:
                logger.warning(
                    "invalid_embedding_task",
                    extra={"message_id": message_id.decode()},
                )
                await self.redis_client.xack(self.STREAM_KEY, self.CONSUMER_GROUP, message_id)
                return
            
            note_id = UUID(note_id_str)
            user_id = UUID(user_id_str)
            
            logger.info(
                "embedding_task_processing",
                extra={
                    "note_id": str(note_id),
                    "content_len": len(content),
                }
            )
            
            # Generate embedding
            embedding = await self.embedding_service.embed_text(content)
            
            if embedding is None:
                logger.error(
                    "embedding_generation_failed_in_worker",
                    extra={"note_id": str(note_id)},
                )
                # Don't acknowledge failed messages, retry later
                return
            
            # Store embedding in database
            await self._store_embedding(note_id, user_id, embedding)
            
            # Acknowledge message
            await self.redis_client.xack(self.STREAM_KEY, self.CONSUMER_GROUP, message_id)
            
            logger.info(
                "embedding_stored",
                extra={
                    "note_id": str(note_id),
                    "embedding_dim": len(embedding),
                }
            )
        
        except Exception as e:
            logger.error(
                f"message_processing_error: {e}",
                extra={"message_id": message_id.decode()},
                exc_info=True,
            )
    
    async def _store_embedding(self, note_id: UUID, user_id: UUID, embedding: list[float]):
        """Store embedding in PostgreSQL."""
        async with self.async_session_maker() as session:
            try:
                # Update note with embedding using raw SQL
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                
                stmt = update(Note).where(
                    Note.id == note_id,
                    Note.user_id == user_id,
                ).values(
                    embedding=embedding_str,
                    embedding_generated_at=datetime.utcnow(),
                )
                
                await session.execute(stmt)
                await session.commit()
                
                logger.debug(f"embedding_stored_in_db: {note_id}")
            
            except Exception as e:
                await session.rollback()
                logger.error(f"embedding_store_error: {e}", exc_info=True)
                raise


async def main():
    """Entry point for worker."""
    settings = Settings()
    worker = EmbeddingWorker(settings)
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
