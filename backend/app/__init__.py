from contextlib import asynccontextmanager
import signal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.auth import router as auth_router
from app.api.google_calendar import router as google_calendar_router
from app.api.assets import router as assets_router
from app.api.jobs import router as jobs_router
from app.api.notes import router as notes_router
from app.api.note_links import router as note_links_router
from app.api.notifications import router as notifications_router
from app.api.search import router as search_router
from app.api.segments import router as segments_router
from app.api.schedules import router as schedules_router
from app.api.upload import router as upload_router
from app.api.sse import sync_sse_router
from app.services.transcription_results_consumer import transcription_results_consumer
from app.services.ocr_processor_worker import get_ocr_processor_worker
from app.utils.logger import get_logger
from app.api.sse.sse_manager import SSEManager

logger = get_logger(__name__)


sse_manager = SSEManager()  # Get singleton instance
original_sigint = signal.getsignal(signal.SIGINT)
original_sigterm = signal.getsignal(signal.SIGTERM)

def signal_exit(signum, frame):
    """
    Signal handler for SIGINT (Ctrl+C) and SIGTERM.
    
    This is called SYNCHRONOUSLY when signal is received.
    Cannot use 'await' here, so we call synchronous method on sse_manager.
    """
    signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
    logger.info(f"🛑 Received {signal_name}, initiating graceful shutdown...")
    
    # Call synchronous method to notify all SSE connections
    # This sends shutdown messages to all queues without awaiting
    sse_manager.signal_shutdown()
    
    if callable(original_sigint):
        original_sigint(signum, frame)
    # Note: We DON'T call sys.exit() here
    # Let Uvicorn's signal handler run after this to properly shutdown


# Register signal handlers
signal.signal(signal.SIGINT, signal_exit)
signal.signal(signal.SIGTERM, signal_exit)
logger.info("✅ Signal handlers registered for SIGINT and SIGTERM")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    # Start transcription results consumer
    try:
        await transcription_results_consumer.start()
    except Exception as exc:
        logger.warning(f"Transcription results consumer disabled: {exc}")

    # Start OCR processor worker in background
    import asyncio
    ocr_worker = get_ocr_processor_worker()
    ocr_worker_task = asyncio.create_task(ocr_worker.start())

    try:
        yield
    finally:
        await transcription_results_consumer.stop()
        # Stop OCR worker
        await ocr_worker.stop()
        # Cancel the worker task
        if not ocr_worker_task.done():
            ocr_worker_task.cancel()
            try:
                await ocr_worker_task
            except asyncio.CancelledError:
                pass

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Backend API for Cortex Scheduling System",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router, prefix=settings.API_STR)
app.include_router(google_calendar_router, prefix=settings.API_STR)
app.include_router(schedules_router, prefix=settings.API_STR)
app.include_router(notes_router, prefix=settings.API_STR)
app.include_router(note_links_router, prefix=settings.API_STR)
app.include_router(assets_router, prefix=settings.API_STR)
app.include_router(segments_router, prefix=settings.API_STR)
app.include_router(jobs_router, prefix=settings.API_STR)
app.include_router(search_router, prefix=settings.API_STR)
app.include_router(notifications_router, prefix=settings.API_STR)
app.include_router(upload_router, prefix=settings.API_STR)
app.include_router(sync_sse_router, prefix=settings.API_STR)

@app.get("/")
def read_root():
    """Root endpoint"""
    return {
        "message": "Cortex API",
        "version": settings.PROJECT_VERSION,
        "api_docs": "/docs"
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "OK"}
