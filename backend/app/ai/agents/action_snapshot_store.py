"""ActionSnapshotStore — lưu snapshot trạng thái trước khi mutating tool thực thi.
Two-layer:
  1. Redis: 24h hot (undo support)
  2. PostgreSQL: 90d audit trail (Layer 7)
Key format: revert:snapshot:{user_id}:{action_id}
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

import redis.asyncio as redis
from sqlalchemy import text

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

SNAPSHOT_TTL_SECONDS = 86_400  # 24 giờ
KEY_PREFIX = "revert:snapshot"

# Session factory for the audit write, overridable for tests.
#
# In production the module-level `AsyncSessionLocal` is correct: one
# process, one event loop, one pooled engine. Under pytest-asyncio each test
# gets a fresh loop while that engine's pool holds connections bound to
# whichever loop first initialised it, so the write can silently go through
# the `except Exception: logger.warning(...)` in `save()` on some tests and
# not others — a real row never lands, but nothing fails loudly. Same root
# cause, same fix, as the session-factory override pattern used by tests
# elsewhere in the codebase.
_audit_session_factory_override = None


def set_audit_session_factory(factory) -> None:
    """Point the audit write at a specific session factory (tests only)."""
    global _audit_session_factory_override
    _audit_session_factory_override = factory


def _open_audit_session():
    if _audit_session_factory_override is not None:
        return _audit_session_factory_override()
    from app.database_async import AsyncSessionLocal

    return AsyncSessionLocal()


@dataclass
class ActionSnapshot:
    tool_name: str
    user_id: str
    conversation_id: str
    snapshot: dict
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: float = field(default_factory=time.time)
    reverted_at: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ActionSnapshot":
        return cls(**data)


class ActionSnapshotStore:
    """
    Redis-backed store cho ActionSnapshot.

    Phương thức:
    - save(snapshot) -> action_id
    - get(user_id, action_id) -> ActionSnapshot | None
    - mark_reverted(user_id, action_id) -> bool
    - list_recent(user_id, limit) -> list[ActionSnapshot]
    """

    @staticmethod
    async def _get_client() -> redis.Redis:
        return redis.from_url(settings.REDIS_URL, decode_responses=True)

    @staticmethod
    def _key(user_id: str, action_id: str) -> str:
        return f"{KEY_PREFIX}:{user_id}:{action_id}"

    async def save(self, snapshot: ActionSnapshot,
                   db_session=None) -> str:
        """Lưu snapshot vào Redis (+ PostgreSQL nếu có db_session). Trả về action_id."""
        try:
            client = await self._get_client()
            key = self._key(snapshot.user_id, snapshot.action_id)
            await client.setex(key, SNAPSHOT_TTL_SECONDS, json.dumps(snapshot.to_dict()))
            logger.info(f"Saved action snapshot: {snapshot.action_id} tool={snapshot.tool_name}")
        except Exception as exc:
            logger.error(f"Failed to save action snapshot to Redis: {exc}", exc_info=True)

        # Deliberately NOT the caller's session.
        #
        # This write is best-effort audit history, but the recovery it used
        # to do — rolling back the caller's session so a failed statement
        # didn't leave the transaction aborted — expires every ORM object
        # that session holds. The agent's request session holds the live
        # `conv`, so one failed audit INSERT made the very next `conv.id`
        # raise MissingGreenlet and the whole chat turn return 500 *after*
        # the user's task had already been created. A best-effort write must
        # not be able to break the request that triggered it, so it gets its
        # own session and the caller's is never touched.
        if db_session is not None:
            try:
                async with _open_audit_session() as audit_session:
                    await self._write_history(audit_session, snapshot)
            except Exception as exc:
                logger.warning(f"Failed to save action snapshot to PG (non-fatal): {exc}")

        return snapshot.action_id

    async def _write_history(self, db_session, snapshot: "ActionSnapshot") -> None:
        """The audit INSERT, on a session of its own."""
        if True:  # keeps the original body's indentation
            try:
                await db_session.execute(
                    text("""
                        INSERT INTO action_history
                            (user_id, conversation_id, tool_name, action_type,
                             action_id, before_state, created_at)
                        VALUES
                            (:uid, :conv_id, :tool, :atype,
                             :aid, CAST(:state AS jsonb), to_timestamp(:created))
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "uid": snapshot.user_id,
                        "conv_id": snapshot.conversation_id,
                        "tool": snapshot.tool_name,
                        "atype": "snapshot",
                        "aid": snapshot.action_id,
                        "state": json.dumps(snapshot.snapshot),
                        "created": snapshot.created_at,
                    },
                )
                await db_session.commit()
                logger.info(f"Saved action snapshot to PG: {snapshot.action_id}")
            except Exception as exc:
                logger.warning(f"Failed to save action snapshot to PG (non-fatal): {exc}")
                # Rolling back is safe now: this session belongs to this
                # method and holds no ORM objects anyone else is using.
                try:
                    await db_session.rollback()
                except Exception as rb_exc:
                    logger.warning(f"Rollback after PG snapshot save failure also failed: {rb_exc}")

    async def get(self, user_id: str, action_id: str) -> Optional[ActionSnapshot]:
        """Lấy snapshot theo user_id + action_id. Trả None nếu không tồn tại / expired."""
        try:
            client = await self._get_client()
            key = self._key(user_id, action_id)
            data = await client.get(key)
            if data is None:
                return None
            return ActionSnapshot.from_dict(json.loads(data))
        except Exception as exc:
            logger.error(f"Failed to get action snapshot: {exc}", exc_info=True)
            return None

    async def mark_reverted(self, user_id: str, action_id: str,
                            db_session=None) -> bool:
        """
        Đánh dấu snapshot đã được revert (idempotent guard).
        Trả False nếu snapshot không tồn tại hoặc đã revert rồi.
        """
        try:
            client = await self._get_client()
            key = self._key(user_id, action_id)
            data = await client.get(key)
            if data is None:
                return False

            snapshot = ActionSnapshot.from_dict(json.loads(data))
            if snapshot.reverted_at is not None:
                logger.warning(f"Action {action_id} already reverted at {snapshot.reverted_at}")
                return False

            snapshot.reverted_at = time.time()
            # Giữ nguyên TTL còn lại
            ttl = await client.ttl(key)
            if ttl > 0:
                await client.setex(key, ttl, json.dumps(snapshot.to_dict()))

            if db_session is not None:
                # Own session, same reasoning as save(): `ctx.async_db()` in
                # CommandRegistry.revert_command() is caller-owned and may be
                # reused for more work in the same turn after this returns.
                # A failed UPDATE rolling back *that* session would expire
                # whatever it holds — this write must not be able to do that.
                try:
                    async with _open_audit_session() as audit_session:
                        await audit_session.execute(
                            text("""
                                UPDATE action_history
                                SET is_reverted = TRUE, reverted_at = NOW()
                                WHERE action_id = :aid
                            """),
                            {"aid": action_id},
                        )
                        await audit_session.commit()
                except Exception as exc:
                    logger.warning(f"Failed to mark_reverted in PG (non-fatal): {exc}")

            return True
        except Exception as exc:
            logger.error(f"Failed to mark_reverted: {exc}", exc_info=True)
            return False

    async def list_recent(self, user_id: str, limit: int = 10) -> list[ActionSnapshot]:
        """
        Liệt kê các snapshot gần nhất của user (chỉ chưa bị revert).

        QUAN TRỌNG: Redis không hỗ trợ range query tốt trên arbitrary keys.
        Implementation dùng SCAN pattern — chấp nhận được vì limit nhỏ.
        Nếu cần scale, thêm Redis Sorted Set index riêng.
        """
        try:
            client = await self._get_client()
            pattern = f"{KEY_PREFIX}:{user_id}:*"
            snapshots = []

            async for key in client.scan_iter(pattern):
                data = await client.get(key)
                if data:
                    snap = ActionSnapshot.from_dict(json.loads(data))
                    if snap.reverted_at is None:
                        snapshots.append(snap)

            # Sort by created_at DESC, take limit
            snapshots.sort(key=lambda s: s.created_at, reverse=True)
            return snapshots[:limit]
        except Exception as exc:
            logger.error(f"Failed to list_recent snapshots: {exc}", exc_info=True)
            return []


# Singleton
_store: Optional[ActionSnapshotStore] = None


def get_snapshot_store() -> ActionSnapshotStore:
    global _store
    if _store is None:
        _store = ActionSnapshotStore()
    return _store
