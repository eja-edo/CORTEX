"""ActionSnapshotStore — lưu snapshot trạng thái trước khi mutating tool thực thi.
Dùng Redis với TTL 24h. Key format: revert:snapshot:{user_id}:{action_id}
"""

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Optional

import redis.asyncio as redis

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

SNAPSHOT_TTL_SECONDS = 86_400  # 24 giờ
KEY_PREFIX = "revert:snapshot"


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

    async def save(self, snapshot: ActionSnapshot) -> str:
        """Lưu snapshot vào Redis. Trả về action_id."""
        try:
            client = await self._get_client()
            key = self._key(snapshot.user_id, snapshot.action_id)
            await client.setex(key, SNAPSHOT_TTL_SECONDS, json.dumps(snapshot.to_dict()))
            logger.info(f"Saved action snapshot: {snapshot.action_id} tool={snapshot.tool_name}")
            return snapshot.action_id
        except Exception as exc:
            logger.error(f"Failed to save action snapshot: {exc}", exc_info=True)
            raise

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

    async def mark_reverted(self, user_id: str, action_id: str) -> bool:
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
