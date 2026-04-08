from contextlib import asynccontextmanager
import signal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.database import engine
from app.models import Base
from app.api.auth import router as auth_router
from app.api.google_calendar import router as google_calendar_router
from app.api.notes import router as notes_router
from app.api.schedules import router as schedules_router
from app.api.upload import router as upload_router
from app.api.sse import sync_sse_router
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
    try:
        Base.metadata.create_all(bind=engine)
    except SQLAlchemyError:
        logger.exception("Database is not available during startup; skipping table creation.")

    yield

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
