"""Tool context for providing runtime access to database and user context."""

from uuid import UUID
from typing import Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ToolContext:
    """
    Runtime context for tool execution.
    
    Provides:
    - User ID (from authenticated session, never from LLM)
    - Workspace ID (optional, scopes operations)
    - Database access (both sync and async)
    
    Security Critical:
    - user_id is ALWAYS from the authenticated session
    - Never from tool arguments
    - Every tool must use ctx.user_id, not args.get("user_id")
    """

    def __init__(
        self,
        user_id: UUID,
        async_db: AsyncSession,
        workspace_id: Optional[UUID] = None,
    ):
        """Initialize tool context with user and database access."""
        self.user_id = user_id
        self.workspace_id = workspace_id
        self._async_db = async_db
        self._sync_db: Optional[Session] = None

    def get_sync_db(self) -> Session:
        """Get or create a sync database session."""
        if self._sync_db is None:
            self._sync_db = SessionLocal()
        return self._sync_db

    @asynccontextmanager
    async def async_db(self):
        """
        Async context manager for database access.
        Uses the existing async session.
        """
        try:
            yield self._async_db
        except Exception as exc:
            logger.error(f"Error in async_db context: {exc}", exc_info=True)
            raise

    def __enter__(self):
        """Sync context manager entry."""
        return self.get_sync_db()

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Sync context manager exit."""
        if self._sync_db:
            self._sync_db.close()
            self._sync_db = None

    def close(self):
        """Cleanup resources."""
        if self._sync_db:
            self._sync_db.close()
            self._sync_db = None

    def __repr__(self) -> str:
        return f"ToolContext(user_id={self.user_id}, workspace_id={self.workspace_id})"
