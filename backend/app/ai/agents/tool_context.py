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
    - Project ID (optional, scopes operations)
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
        conversation_id: Optional[UUID] = None,
        project_id: Optional[UUID] = None,
    ):
        """Initialize tool context with user and database access.

        `project_id` là ngữ cảnh container duy nhất (DESIGN 11.4).

        **`None` là giá trị bình thường, không phải thiếu sót.** Chat qua DM
        Mezon không có dự án nào đang mở, và một tool từ chối chạy vì thiếu
        ngữ cảnh sẽ chết đúng ở bề mặt hay dùng nhất. Tool nào cần một dự án
        cụ thể thì hỏi tên qua `project_ref` (9.2), không đọc ngầm ở đây.
        """
        self.user_id = user_id
        self.project_id = project_id
        self.conversation_id = conversation_id
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
        Rolls back the session if an exception occurs to prevent transaction corruption.
        """
        try:
            yield self._async_db
        except Exception as exc:
            logger.error(f"Error in async_db context: {exc}", exc_info=True)
            try:
                await self._async_db.rollback()
            except Exception as rb_exc:
                logger.warning(f"Rollback after error failed (non-fatal): {rb_exc}")
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
        return f"ToolContext(user_id={self.user_id}, project_id={self.project_id})"
