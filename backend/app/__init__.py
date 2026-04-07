import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.database import engine
from app.models import Base, Note  # noqa: F401
from app.api.auth import router as auth_router
from app.api.notes import router as notes_router
from app.api.schedules import router as schedules_router

logger = logging.getLogger(__name__)


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
app.include_router(schedules_router, prefix=settings.API_STR)
app.include_router(notes_router, prefix=settings.API_STR)

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
