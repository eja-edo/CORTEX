# Configure logging FIRST before any other imports to suppress SQLAlchemy
from app.utils.logger import _configure_root_logger, get_logger
_configure_root_logger()

from contextlib import asynccontextmanager
import signal
import threading
import asyncio
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.auth import router as auth_router
from app.api.agent import router as agent_router
from app.api.google_calendar import router as google_calendar_router
from app.api.assets import router as assets_router
from app.api.notes import router as notes_router
from app.api.notifications import router as notifications_router
from app.api.schedules import router as schedules_router
from app.api.upload import router as upload_router
from app.api.knowledge import router as knowledge_router
from app.api.internal import router as internal_router
from app.api.workspaces import router as workspaces_router
from app.api.sse import sync_sse_router
from app.services.transcription_results_consumer import transcription_results_consumer
from app.services.llm_processor_worker_fixed import get_llm_processor_worker
from app.services.reminder_worker import ReminderWorker
from app.services.google_sync_worker import GoogleSyncWorker
from app.api.sse.sse_manager import SSEManager

logger = get_logger(__name__)


class WorkerThread:
    """Run an async worker in a separate thread with its own event loop."""
    
    def __init__(self, name: str, worker):
        self.name = name
        self.worker = worker
        self.thread: Optional[threading.Thread] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
    
    def start(self):
        """Start worker in background thread."""
        if self._running:
            return
        
        self._running = True
        self.thread = threading.Thread(
            target=self._run,
            name=f"Worker-{self.name}",
            daemon=False
        )
        self.thread.start()
        logger.info(f"✅ Started {self.name} worker in separate thread")
    
    def _run(self):
        """Run worker in separate event loop."""
        try:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self.worker.start())
        except KeyboardInterrupt:
            logger.info(f"{self.name} worker interrupted")
        except Exception as exc:
            logger.error(f"{self.name} worker crashed: {exc}", exc_info=True)
        finally:
            self._running = False
            if self._loop:
                self._loop.close()
    
    def stop(self):
        """Stop worker and wait for thread."""
        if not self._running or not self._loop:
            return
        
        self._running = False
        
        # Signal worker to stop via its event loop
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self.worker.stop(),
                self._loop
            )
            try:
                future.result(timeout=5)
            except Exception as exc:
                logger.warning(f"Error stopping {self.name}: {exc}")
        
        # Wait for thread to finish
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
            if self.thread.is_alive():
                logger.warning(f"{self.name} thread did not stop gracefully")


sse_manager = SSEManager()  # Get singleton instance
original_sigint = signal.getsignal(signal.SIGINT)
original_sigterm = signal.getsignal(signal.SIGTERM)

# Global worker threads
_llm_worker_thread: Optional[WorkerThread] = None
_reminder_worker_thread: Optional[WorkerThread] = None
_google_sync_worker_thread: Optional[WorkerThread] = None

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
    global _llm_worker_thread, _reminder_worker_thread, _google_sync_worker_thread
    
    # Start transcription results consumer
    try:
        await transcription_results_consumer.start()
    except Exception as exc:
        logger.warning(f"Transcription results consumer disabled: {exc}")

    # OCR processing is handled by external OCR service
    logger.info("🔧 OCR Service Mode: EXTERNAL (OCR service handles processing)")

    # Start LLM processor worker in separate thread
    llm_worker = get_llm_processor_worker()
    _llm_worker_thread = WorkerThread("LLM", llm_worker)
    _llm_worker_thread.start()

    # Start ReminderWorker in separate thread
    reminder_worker = ReminderWorker()
    _reminder_worker_thread = WorkerThread("Reminder", reminder_worker)
    _reminder_worker_thread.start()

    # Start GoogleSyncWorker in separate thread
    google_sync_worker = GoogleSyncWorker()
    _google_sync_worker_thread = WorkerThread("GoogleSync", google_sync_worker)
    _google_sync_worker_thread.start()

    try:
        yield
    finally:
        await transcription_results_consumer.stop()
        
        # Stop all workers
        if _reminder_worker_thread:
            _reminder_worker_thread.stop()
        if _google_sync_worker_thread:
            _google_sync_worker_thread.stop()
        if _llm_worker_thread:
            _llm_worker_thread.stop()

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
app.include_router(agent_router, prefix=settings.API_STR)
app.include_router(google_calendar_router, prefix=settings.API_STR)
app.include_router(schedules_router, prefix=settings.API_STR)
app.include_router(notes_router, prefix=settings.API_STR)
app.include_router(assets_router, prefix=settings.API_STR)
app.include_router(notifications_router, prefix=settings.API_STR)
app.include_router(upload_router, prefix=settings.API_STR)
app.include_router(knowledge_router, prefix=settings.API_STR)
app.include_router(workspaces_router, prefix=settings.API_STR)
app.include_router(sync_sse_router, prefix=settings.API_STR)

# Internal service-to-service endpoints (not exposed to internet)
app.include_router(internal_router)

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
