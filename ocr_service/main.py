"""
OCR Service Entry Point

Standalone microservice for OCR video processing using FastAPI.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from worker.consumer import OCRConsumer
from config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# Global consumer instance
_consumer: Optional[OCRConsumer] = None
_consumer_task: Optional[asyncio.Task] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage OCR consumer lifecycle."""
    global _consumer, _consumer_task
    
    # Startup: Start OCR consumer
    logger.info("OCR Service starting...")
    logger.info(f"  Redis: {settings.redis_url}")
    logger.info(f"  MongoDB: {settings.mongodb_url}")
    logger.info(f"  MinIO: {settings.minio_endpoint}")
    logger.info(f"  Consumer group: {settings.consumer_group}")
    
    _consumer = OCRConsumer()
    _consumer_task = asyncio.create_task(_consumer.start())
    
    try:
        yield
    finally:
        # Shutdown: Stop OCR consumer gracefully
        logger.info("Stopping OCR consumer...")
        if _consumer:
            await _consumer.stop()
        if _consumer_task and not _consumer_task.done():
            _consumer_task.cancel()
            try:
                await _consumer_task
            except asyncio.CancelledError:
                pass
        logger.info("OCR Service stopped.")


# Initialize FastAPI app
app = FastAPI(
    title="OCR Service",
    description="Standalone OCR microservice for video processing",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "ocr-service",
        "consumer_group": settings.consumer_group,
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check - verifies consumer is running."""
    if _consumer and _consumer_task and not _consumer_task.done():
        return {
            "status": "ready",
            "consumer_running": True,
        }
    return {
        "status": "not ready",
        "consumer_running": False,
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8007,
        log_level=settings.log_level.lower(),
    )
