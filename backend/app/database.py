from contextlib import contextmanager
from typing import Generator
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from app.config import settings

# Create the database engine
engine = create_engine(
    settings.DATABASE_URL,
    echo=os.getenv("SQLALCHEMY_ECHO", "false").lower() == "true",
    future=True
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    future=True
)

def get_db() -> Generator[Session, None, None]:
    """Dependency to get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def sync_session() -> Generator[Session, None, None]:
    """
    Context manager cho sync SQLAlchemy session.

    Dùng cho code CHẮC CHẮN chạy ngoài event loop (worker thread qua
    asyncio.to_thread, script CLI, test sync). KHÔNG dùng trong async
    context — sẽ block event loop.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
