# Revert Action System — Design Document

> **Mục tiêu tài liệu này:** Cung cấp đủ ngữ cảnh và đặc tả kỹ thuật để subagent implement hoàn chỉnh cơ chế revert (undo) cho mọi mutating tool action trong hệ thống Cortex Agent backend.

---

## 1. Phân tích hiện trạng

### 1.1 Kiến trúc hiện tại

```
AgentService
 └── handle_streaming_generator() / handle()
      ├── _build_history_contents()     ← load conversation history
      ├── ModelClient.stream_with_fallback()  ← LLM call
      ├── ToolRegistry.execute(tool_name, args, ctx)
      │    └── ToolDefinition.validate_and_execute()
      │         └── handler(args, ctx) → dict   ← THỰC THI THẬT, KHÔNG THỂ REVERT
      └── ConversationStore.save_message()      ← lưu tool_input + tool_output
```

### 1.2 Các tool MUTATING (gây thay đổi dữ liệu)

| Tool | Hành động | Reversible? Hiện tại |
|---|---|---|
| `create_note` | INSERT note row | ❌ Không — không có soft delete qua agent |
| `update_note` | PATCH note (OT patch) | ❌ Không — không lưu snapshot trước |
| `create_schedule` | INSERT schedule + Google Sync | ❌ Không — Google sync không rollback |
| `update_schedule` | UPDATE schedule fields | ❌ Không — không lưu trạng thái trước |

Các tool READ-ONLY (không cần revert):
- `search_notes`, `get_schedules`, `search_knowledge`, `summarize_asset`, `get_notifications`, `web_search`, `neural_search`, `deep_research`

### 1.3 Vấn đề cốt lõi

Khi LLM gọi `create_note` hoặc `update_note`, hệ thống:
1. Thực thi ngay, commit vào DB.
2. Lưu `tool_output` vào `AgentMessage` (role=tool) — có `id` của record được tạo/sửa.
3. **Không lưu snapshot trạng thái trước** khi sửa.
4. **Không có endpoint nào** cho agent tự gọi để undo.

---

## 2. Thiết kế hệ thống Revert

### 2.1 Nguyên tắc thiết kế

1. **Snapshot trước khi mutate** — Mọi mutating handler phải lưu trạng thái cũ trước khi thực thi.
2. **Revert là một tool** — Agent có thể chủ động gọi `revert_action` bằng ngôn ngữ tự nhiên.
3. **Revert lưu trong Redis** (TTL 24h) — Không tạo bảng DB mới; nhẹ và tự dọn.
4. **Không revert Google Sync** trong MVP — Chỉ revert DB local; ghi chú rõ với user.
5. **Idempotent** — Gọi revert 2 lần trên cùng action_id phải trả lỗi, không corrupt data.
6. **Audit trail** — Mỗi revert action tạo một message mới trong conversation.

### 2.2 Data model: ActionSnapshot

Mỗi mutating action lưu một **ActionSnapshot** vào Redis với key:

```
revert:snapshot:{user_id}:{action_id}
```

```python
@dataclass
class ActionSnapshot:
    action_id: str          # uuid4 — primary key cho revert
    tool_name: str          # "create_note" | "update_note" | ...
    user_id: str            # owner — bắt buộc match khi revert
    conversation_id: str    # để trace
    created_at: float       # time.time()
    reverted_at: float | None  # None nếu chưa revert
    
    # Snapshot data — khác nhau tùy tool
    snapshot: dict          # xem §2.3
```

TTL: **86400 giây (24 giờ)** — sau đó không thể revert nữa.

### 2.3 Snapshot data theo tool

#### `create_note`
```python
snapshot = {
    "op": "create_note",
    "note_id": str,          # ID của note vừa tạo → DELETE khi revert
    "workspace_id": str,
}
```
**Revert:** soft-delete note (set `is_deleted=True`).

#### `update_note`
```python
snapshot = {
    "op": "update_note",
    "note_id": str,
    "prev_content": str,     # full content TRƯỚC khi patch
    "prev_version": int,     # version number TRƯỚC khi patch
}
```
**Revert:** build patch từ `current_content → prev_content`, apply patch.

#### `create_schedule`
```python
snapshot = {
    "op": "create_schedule",
    "schedule_id": str,      # ID của schedule vừa tạo → DELETE khi revert
}
```
**Revert:** hard-delete schedule (không có soft delete trong model hiện tại).
> ⚠️ Google Calendar sync đã chạy — cần thông báo user tự xóa trên Google Calendar.

#### `update_schedule`
```python
snapshot = {
    "op": "update_schedule",
    "schedule_id": str,
    "prev_fields": {
        "title": str | None,
        "start_time": str,   # ISO 8601
        "end_time": str,     # ISO 8601
        "description": str | None,
        "is_completed": bool,
    }
}
```
**Revert:** gọi lại `update_schedule_fields` với `prev_fields`.

---

## 3. Các thành phần cần tạo mới

### 3.1 File mới cần tạo

```
backend/app/services/agent/
├── action_snapshot_store.py      ← NEW: Redis CRUD cho ActionSnapshot
└── tools/
    └── revert_action.py          ← NEW: Tool để agent gọi revert
```

### 3.2 File cần sửa

```
backend/app/services/agent/tools/
├── create_note.py       ← save snapshot trước khi return
├── update_note.py       ← save snapshot với prev_content
├── create_schedule.py   ← save snapshot trước khi return
├── update_schedule.py   ← save snapshot với prev_fields
└── __init__.py          ← register thêm REVERT_ACTION_DEFINITION
```

---

## 4. Đặc tả chi tiết từng file

### 4.1 `action_snapshot_store.py` (TẠO MỚI)

```python
"""
ActionSnapshotStore — lưu snapshot trạng thái trước khi mutating tool thực thi.
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
    - save(snapshot) → action_id
    - get(user_id, action_id) → ActionSnapshot | None
    - mark_reverted(user_id, action_id) → bool
    - list_recent(user_id, limit) → list[ActionSnapshot]
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
            logger.info(f"✅ Saved action snapshot: {snapshot.action_id} tool={snapshot.tool_name}")
            return snapshot.action_id
        except Exception as exc:
            logger.error(f"❌ Failed to save action snapshot: {exc}", exc_info=True)
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
            logger.error(f"❌ Failed to get action snapshot: {exc}", exc_info=True)
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
            logger.error(f"❌ Failed to mark_reverted: {exc}", exc_info=True)
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
            logger.error(f"❌ Failed to list_recent snapshots: {exc}", exc_info=True)
            return []


# Singleton
_store: Optional[ActionSnapshotStore] = None

def get_snapshot_store() -> ActionSnapshotStore:
    global _store
    if _store is None:
        _store = ActionSnapshotStore()
    return _store
```

---

### 4.2 Sửa `create_note.py`

**Thêm vào cuối `create_note_handler`, trước `return`:**

```python
# --- REVERT SNAPSHOT ---
from app.services.agent.action_snapshot_store import ActionSnapshot, get_snapshot_store

snapshot = ActionSnapshot(
    tool_name="create_note",
    user_id=str(ctx.user_id),
    conversation_id=str(getattr(ctx, "conversation_id", "")),
    snapshot={
        "op": "create_note",
        "note_id": str(note.id),
        "workspace_id": str(note.workspace_id),
    },
)
action_id = await get_snapshot_store().save(snapshot)
# -----------------------

return {
    "id": str(note.id),
    "workspace_id": str(note.workspace_id),
    "created_at": note.created_at.isoformat(),
    "action_id": action_id,   # ← THÊM: trả về để LLM biết có thể revert
    "revert_hint": "Bạn có thể yêu cầu hoàn tác hành động này bằng action_id trên.",
    "success": True,
}
```

**QUAN TRỌNG:** Thêm `conversation_id` vào `ToolContext` (xem §4.6).

---

### 4.3 Sửa `update_note.py`

**Capture `prev_content` và `prev_version` TRƯỚC khi patch, sau đó save snapshot:**

```python
# Sau khi fetch current note, TRƯỚC khi build patch:
prev_content = current_content
prev_version = current.version

patch = build_text_patch(current_content, content)
# ... apply patch ...

# --- REVERT SNAPSHOT ---
from app.services.agent.action_snapshot_store import ActionSnapshot, get_snapshot_store

snapshot = ActionSnapshot(
    tool_name="update_note",
    user_id=str(ctx.user_id),
    conversation_id=str(getattr(ctx, "conversation_id", "")),
    snapshot={
        "op": "update_note",
        "note_id": str(note_id),
        "prev_content": prev_content,
        "prev_version": prev_version,
    },
)
action_id = await get_snapshot_store().save(snapshot)
# -----------------------

return {
    "id": str(updated.id),
    "version": updated.version,
    "updated_at": updated.updated_at.isoformat() if updated.updated_at else None,
    "updated": True,
    "action_id": action_id,   # ← THÊM
    "revert_hint": "Bạn có thể hoàn tác cập nhật này bằng action_id trên.",
    "success": True,
}
```

---

### 4.4 Sửa `create_schedule.py`

**Thêm sau khi tạo schedule thành công:**

```python
# --- REVERT SNAPSHOT ---
from app.services.agent.action_snapshot_store import ActionSnapshot, get_snapshot_store

snapshot = ActionSnapshot(
    tool_name="create_schedule",
    user_id=str(ctx.user_id),
    conversation_id=str(getattr(ctx, "conversation_id", "")),
    snapshot={
        "op": "create_schedule",
        "schedule_id": str(schedule.id),
    },
)
action_id = await get_snapshot_store().save(snapshot)
# -----------------------

return {
    "id": str(schedule.id),
    "title": schedule.title,
    "start_time": schedule.start_time.isoformat(),
    "end_time": schedule.end_time.isoformat(),
    "recurrence": schedule.recurrence_rule,
    "created_at": schedule.created_at.isoformat() if schedule.created_at else None,
    "action_id": action_id,   # ← THÊM
    "revert_hint": "Bạn có thể hoàn tác tạo lịch này bằng action_id trên. Lưu ý: Google Calendar sync đã chạy, cần xóa thủ công trên Google.",
    "success": True,
}
```

---

### 4.5 Sửa `update_schedule.py`

**Capture trạng thái cũ TRƯỚC khi update:**

```python
db = SessionLocal()
try:
    svc = ScheduleService(db)
    
    # --- CAPTURE PREV STATE ---
    existing = svc.get_schedule(schedule_id=schedule_id, user_id=ctx.user_id)
    if not existing:
        raise ValueError("Schedule not found or permission denied")
    
    prev_fields = {
        "title": existing.title,
        "start_time": existing.start_time.isoformat(),
        "end_time": existing.end_time.isoformat(),
        "description": existing.description,
        "is_completed": existing.is_completed,
    }
    # --------------------------

    schedule = svc.update_schedule_fields(
        schedule_id=schedule_id,
        user_id=ctx.user_id,
        title=args.get("title"),
        start_time=start_time,
        end_time=end_time,
        description=args.get("description"),
        is_completed=args.get("is_completed"),
    )

    # --- REVERT SNAPSHOT ---
    from app.services.agent.action_snapshot_store import ActionSnapshot, get_snapshot_store
    
    snapshot = ActionSnapshot(
        tool_name="update_schedule",
        user_id=str(ctx.user_id),
        conversation_id=str(getattr(ctx, "conversation_id", "")),
        snapshot={
            "op": "update_schedule",
            "schedule_id": str(schedule_id),
            "prev_fields": prev_fields,
        },
    )
    action_id = await get_snapshot_store().save(snapshot)
    # -----------------------

    return {
        "id": str(schedule.id),
        "title": schedule.title,
        "start_time": schedule.start_time.isoformat(),
        "end_time": schedule.end_time.isoformat(),
        "is_completed": schedule.is_completed,
        "updated_at": schedule.updated_at.isoformat() if schedule.updated_at else None,
        "action_id": action_id,   # ← THÊM
        "revert_hint": "Bạn có thể hoàn tác cập nhật lịch này bằng action_id trên.",
        "success": True,
    }
```

> **Lưu ý:** `update_schedule_handler` hiện là sync (`db = SessionLocal()`). Cần wrap snapshot save vào event loop hoặc chuyển sang async. Xem §4.7 về cách handle mixed sync/async.

---

### 4.6 Sửa `tool_context.py` — thêm `conversation_id`

```python
class ToolContext:
    def __init__(
        self,
        user_id: UUID,
        async_db: AsyncSession,
        workspace_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,   # ← THÊM
    ):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.conversation_id = conversation_id     # ← THÊM
        self._async_db = async_db
        self._sync_db: Optional[Session] = None
```

**Sửa tất cả chỗ tạo `ToolContext` trong `agent_service.py`:**

```python
ctx = ToolContext(
    user_id=user_id,
    async_db=self.db,
    workspace_id=workspace_id,
    conversation_id=conv.id,   # ← THÊM
)
```

---

### 4.7 Xử lý mixed sync/async trong `update_schedule.py`

`update_schedule_handler` dùng `SessionLocal()` (sync DB) nhưng snapshot store là async.
Giải pháp: dùng `asyncio.get_event_loop().run_until_complete()` HOẶC chuyển handler sang async + dùng `run_in_executor` cho phần sync.

**Cách đơn giản nhất — tách snapshot save ra ngoài try/finally của sync DB:**

```python
async def update_schedule_handler(args: dict, ctx: ToolContext) -> dict:
    # ... validate args ...
    
    from app.database import SessionLocal
    result_data = {}
    
    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        existing = svc.get_schedule(schedule_id=schedule_id, user_id=ctx.user_id)
        prev_fields = { ... }  # capture
        
        schedule = svc.update_schedule_fields(...)
        
        result_data = {
            "id": str(schedule.id),
            "prev_fields": prev_fields,
            # ...
        }
    finally:
        db.close()
    
    # Async snapshot save NGOÀI sync DB context
    snapshot = ActionSnapshot(...)
    action_id = await get_snapshot_store().save(snapshot)
    
    result_data["action_id"] = action_id
    result_data["revert_hint"] = "..."
    return result_data
```

**Tương tự cho `create_schedule_handler`** — hiện tại cũng dùng `SessionLocal()`.

---

### 4.8 `tools/revert_action.py` (TẠO MỚI — TOOL CHO LLM GỌI)

```python
"""
Revert Action Tool — cho phép agent hoàn tác mutating action gần nhất.

LLM sẽ gọi tool này khi user nói:
- "undo", "hoàn tác", "bỏ đi", "xóa cái vừa tạo", etc.
- "revert action_id abc123"
- "undo the last note I created"
"""

from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.services.agent.action_snapshot_store import get_snapshot_store
from app.services.agent.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RevertActionInput(BaseModel):
    action_id: Optional[str] = Field(
        None,
        description="action_id từ kết quả của tool trước. Nếu không cung cấp, sẽ revert action gần nhất."
    )


async def revert_action_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Hoàn tác một action đã thực hiện bởi agent.
    
    Logic:
    1. Lấy snapshot từ Redis (theo action_id hoặc action mới nhất của user)
    2. Validate ownership (user_id phải khớp)
    3. Validate chưa revert (idempotent guard)
    4. Thực thi revert tương ứng với op type
    5. Đánh dấu đã revert trong Redis
    """
    store = get_snapshot_store()
    user_id_str = str(ctx.user_id)
    action_id = args.get("action_id")

    # --- Tìm snapshot ---
    if action_id:
        snapshot = await store.get(user_id_str, action_id)
        if snapshot is None:
            return {
                "success": False,
                "error": f"Không tìm thấy action_id '{action_id}'. Có thể đã hết hạn (24h) hoặc action_id không đúng.",
            }
    else:
        # Lấy action gần nhất chưa revert
        recent = await store.list_recent(user_id_str, limit=1)
        if not recent:
            return {
                "success": False,
                "error": "Không tìm thấy action nào có thể hoàn tác. Các action chỉ có thể hoàn tác trong vòng 24h.",
            }
        snapshot = recent[0]

    # --- Validate ownership ---
    if snapshot.user_id != user_id_str:
        logger.warning(f"Revert ownership mismatch: snapshot.user_id={snapshot.user_id} ctx.user_id={user_id_str}")
        return {
            "success": False,
            "error": "Permission denied: action này không thuộc về bạn.",
        }

    # --- Idempotent guard ---
    if snapshot.reverted_at is not None:
        return {
            "success": False,
            "error": f"Action này đã được hoàn tác vào lúc {datetime.fromtimestamp(snapshot.reverted_at, tz=timezone.utc).isoformat()}.",
            "already_reverted": True,
        }

    # --- Thực thi revert ---
    op = snapshot.snapshot.get("op")
    try:
        if op == "create_note":
            result = await _revert_create_note(snapshot.snapshot, ctx)
        elif op == "update_note":
            result = await _revert_update_note(snapshot.snapshot, ctx)
        elif op == "create_schedule":
            result = await _revert_create_schedule(snapshot.snapshot, ctx)
        elif op == "update_schedule":
            result = await _revert_update_schedule(snapshot.snapshot, ctx)
        else:
            return {
                "success": False,
                "error": f"Không hỗ trợ revert cho op='{op}'.",
            }
    except Exception as exc:
        logger.error(f"Revert failed for op={op} action_id={snapshot.action_id}: {exc}", exc_info=True)
        return {
            "success": False,
            "error": f"Hoàn tác thất bại: {str(exc)}",
        }

    # --- Đánh dấu đã revert ---
    await store.mark_reverted(user_id_str, snapshot.action_id)

    return {
        "success": True,
        "action_id": snapshot.action_id,
        "tool_name": snapshot.tool_name,
        "op": op,
        "detail": result,
        "message": result.get("message", f"Đã hoàn tác thành công: {op}"),
    }


# ── Revert implementations ──────────────────────────────────────────────────

async def _revert_create_note(snap: dict, ctx: ToolContext) -> dict:
    """Soft-delete note vừa tạo."""
    from uuid import UUID
    from sqlalchemy import select
    from app.models import Note

    note_id = UUID(snap["note_id"])

    async with ctx.async_db() as db:
        stmt = select(Note).where(
            Note.id == note_id,
            Note.user_id == ctx.user_id,
        )
        result = await db.execute(stmt)
        note = result.scalar_one_or_none()

        if not note:
            raise ValueError(f"Note {note_id} không tồn tại hoặc đã bị xóa.")

        if note.is_deleted:
            return {"message": f"Note {note_id} đã bị xóa từ trước.", "note_id": str(note_id)}

        note.is_deleted = True
        await db.flush()

    return {
        "message": f"Đã xóa note '{str(note_id)[:8]}...' (soft delete).",
        "note_id": str(note_id),
    }


async def _revert_update_note(snap: dict, ctx: ToolContext) -> dict:
    """Khôi phục note về nội dung trước khi update."""
    from uuid import UUID
    from app.schemas import NotePatchRequest
    from app.services.notes import NoteService
    from app.utils.note_delta import build_text_patch

    note_id = UUID(snap["note_id"])
    prev_content = snap["prev_content"]

    async with ctx.async_db() as db:
        service = NoteService(db)
        current = await service.get_note(note_id=note_id, user_id=ctx.user_id)
        if current is None:
            raise ValueError(f"Note {note_id} không tồn tại.")

        current_content = await service.materialize_note_content(current)
        if current_content == prev_content:
            return {"message": "Nội dung note đã giống với trạng thái trước, không cần hoàn tác.", "note_id": str(note_id)}

        patch = build_text_patch(current_content, prev_content)
        if not patch:
            raise ValueError("Không thể tạo patch để hoàn tác.")

        payload = NotePatchRequest(version=current.version, patch=patch)
        updated = await service.patch_note(note_id=note_id, user_id=ctx.user_id, payload=payload)
        if updated is None:
            raise ValueError("Version conflict khi hoàn tác. Vui lòng thử lại.")

    return {
        "message": f"Đã khôi phục note về phiên bản trước.",
        "note_id": str(note_id),
        "new_version": updated.version,
    }


async def _revert_create_schedule(snap: dict, ctx: ToolContext) -> dict:
    """Xóa schedule vừa tạo."""
    from uuid import UUID
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    schedule_id = UUID(snap["schedule_id"])

    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        deleted = svc.delete_schedule(schedule_id=schedule_id, user_id=ctx.user_id)
        if not deleted:
            raise ValueError(f"Schedule {schedule_id} không tồn tại hoặc bạn không có quyền xóa.")
    finally:
        db.close()

    return {
        "message": (
            f"Đã xóa schedule '{snap['schedule_id'][:8]}...'.\n"
            "⚠️ Lưu ý: Sự kiện có thể vẫn còn trên Google Calendar — vui lòng xóa thủ công nếu cần."
        ),
        "schedule_id": str(schedule_id),
    }


async def _revert_update_schedule(snap: dict, ctx: ToolContext) -> dict:
    """Khôi phục schedule về trạng thái trước khi update."""
    from uuid import UUID
    from datetime import datetime
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    schedule_id = UUID(snap["schedule_id"])
    prev = snap["prev_fields"]

    start_time = datetime.fromisoformat(prev["start_time"]) if prev.get("start_time") else None
    end_time = datetime.fromisoformat(prev["end_time"]) if prev.get("end_time") else None

    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        schedule = svc.update_schedule_fields(
            schedule_id=schedule_id,
            user_id=ctx.user_id,
            title=prev.get("title"),
            start_time=start_time,
            end_time=end_time,
            description=prev.get("description"),
            is_completed=prev.get("is_completed"),
        )
    finally:
        db.close()

    return {
        "message": f"Đã khôi phục lịch về trạng thái trước.",
        "schedule_id": str(schedule_id),
        "restored_title": schedule.title,
    }


# ── Tool definition ──────────────────────────────────────────────────────────

REVERT_ACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "action_id": {
            "type": "string",
            "description": (
                "action_id từ kết quả của một tool trước (create_note, update_note, "
                "create_schedule, update_schedule). Nếu bỏ trống, sẽ hoàn tác action gần nhất."
            ),
        },
    },
}

REVERT_ACTION_DEFINITION = {
    "name": "revert_action",
    "handler": revert_action_handler,
    "input_model": RevertActionInput,
    "schema": REVERT_ACTION_SCHEMA,
    "description": (
        "Hoàn tác (undo) một action đã thực hiện: tạo note, sửa note, tạo lịch, sửa lịch. "
        "Cung cấp action_id từ kết quả tool trước, hoặc để trống để undo action gần nhất. "
        "Chỉ có thể hoàn tác trong vòng 24 giờ. Mỗi action chỉ có thể hoàn tác một lần."
    ),
}
```

---

### 4.9 Sửa `tools/__init__.py` — register revert tool

```python
from app.services.agent.tools.revert_action import REVERT_ACTION_DEFINITION

def register_all_tools() -> None:
    tools = [
        SEARCH_NOTES_DEFINITION,
        CREATE_NOTE_DEFINITION,
        UPDATE_NOTE_DEFINITION,
        GET_SCHEDULES_DEFINITION,
        CREATE_SCHEDULE_DEFINITION,
        UPDATE_SCHEDULE_DEFINITION,
        SEARCH_KNOWLEDGE_DEFINITION,
        SUMMARIZE_ASSET_DEFINITION,
        GET_NOTIFICATIONS_DEFINITION,
        WEB_SEARCH_DEFINITION,
        NEURAL_SEARCH_DEFINITION,
        DEEP_RESEARCH_DEFINITION,
        REVERT_ACTION_DEFINITION,   # ← THÊM
    ]
    # ...
```

---

### 4.10 Sửa SYSTEM_PROMPT trong `agent_service.py`

Thêm vào phần **TOOL USAGE RULES**:

```
## TOOL USAGE RULES
...
- Available tools: search_notes, create_note, update_note, get_schedules,
  create_schedule, update_schedule, search_knowledge, summarize_asset,
  get_notifications, revert_action.

## REVERT (UNDO) BEHAVIOR
- Khi user nói "undo", "hoàn tác", "bỏ đi", "xóa cái vừa tạo/thêm", 
  "undo lịch vừa tạo", "khôi phục note" → gọi revert_action.
- Nếu có action_id từ turn trước → truyền vào revert_action(action_id=...).
- Nếu không có → gọi revert_action() không có tham số (undo gần nhất).
- Sau khi revert, thông báo rõ cho user những gì đã được hoàn tác và cảnh báo nếu có side effect (Google Calendar).
- KHÔNG tự ý revert nếu user không yêu cầu rõ ràng.
```

---

## 5. Tóm tắt luồng hoàn chỉnh

### Luồng tạo + revert note

```
User: "Tạo note về meeting ngày mai"
  → create_note(content="...", workspace_id="...")
      → INSERT note vào DB
      → save ActionSnapshot to Redis: key=revert:snapshot:{user_id}:{action_id_1}
      → return { id: "xxx", action_id: "action_id_1", revert_hint: "..." }
  ← Agent: "Đã tạo note. action_id: action_id_1"

User: "Hoàn tác đi"
  → revert_action(action_id="action_id_1")
      → get snapshot from Redis
      → validate user_id, reverted_at
      → _revert_create_note: note.is_deleted = True
      → mark_reverted in Redis
      → return { success: True, message: "Đã xóa note..." }
  ← Agent: "Đã hoàn tác tạo note."
```

### Luồng update + revert schedule

```
User: "Đổi tên lịch 'Meeting A' thành 'Meeting B'"
  → get_schedules(...)  [tìm schedule_id]
  → update_schedule(schedule_id="...", title="Meeting B")
      → capture prev_fields = { title: "Meeting A", ... }
      → UPDATE DB
      → save ActionSnapshot to Redis
      → return { ..., action_id: "action_id_2" }
  ← Agent: "Đã đổi tên lịch."

User: "Undo"
  → revert_action(action_id="action_id_2")
      → _revert_update_schedule: restore title="Meeting A"
      → mark_reverted
  ← Agent: "Đã khôi phục lịch về tên 'Meeting A'."
```

---

## 6. Edge cases và handling

| Case | Behavior |
|---|---|
| Revert action đã expired (>24h) | Trả lỗi: "action đã hết hạn" |
| Revert 2 lần cùng action_id | Trả lỗi: "đã hoàn tác rồi" (idempotent) |
| Note bị ai đó sửa sau khi action | update_note revert: version conflict → trả lỗi, yêu cầu manual |
| Redis không available | Snapshot save fail → log error, KHÔNG fail tool chính (non-blocking) |
| Google Calendar sync đã chạy khi revert create_schedule | Revert DB thành công, warn user về Google Calendar |
| action_id từ conversation khác | user_id check ngăn cross-user revert |

---

## 7. Dependency checklist

Trước khi implement, verify:

- [ ] `Note` model có field `is_deleted: bool` (hiện tại `semantic_search.py` đã dùng `n.is_deleted = FALSE` → có)
- [ ] `ScheduleService` có method `delete_schedule(schedule_id, user_id)` → cần kiểm tra / thêm nếu chưa có
- [ ] `ScheduleService` có method `get_schedule(schedule_id, user_id)` → cần kiểm tra / thêm nếu chưa có
- [ ] `NoteService.materialize_note_content(note)` tồn tại → đã dùng trong `update_note.py` → có
- [ ] `build_text_patch` từ `app.utils.note_delta` → đã dùng trong `update_note.py` → có
- [ ] `settings.REDIS_URL` configured → đã dùng trong `embedding_service.py` → có
- [ ] Redis async client (`redis.asyncio`) installed → đã dùng trong `embedding_service.py` → có

---

## 8. Thứ tự implement cho subagent

```
Bước 1: Tạo action_snapshot_store.py
Bước 2: Sửa tool_context.py — thêm conversation_id
Bước 3: Sửa agent_service.py — pass conversation_id vào ToolContext
Bước 4: Sửa create_note.py — thêm snapshot save
Bước 5: Sửa update_note.py — capture prev + save snapshot
Bước 6: Sửa create_schedule.py — async + snapshot save
Bước 7: Sửa update_schedule.py — capture prev + async + snapshot save
Bước 8: Tạo tools/revert_action.py
Bước 9: Sửa tools/__init__.py — register revert_action
Bước 10: Sửa SYSTEM_PROMPT — thêm revert behavior rules
Bước 11: Test từng bước theo luồng §5
```

---

## 9. Testing checklist

```python
# Test 1: create_note → revert
note = await create_note_handler({"content": "test", "workspace_id": ws_id}, ctx)
assert "action_id" in note
result = await revert_action_handler({"action_id": note["action_id"]}, ctx)
assert result["success"] is True
# Verify note is_deleted=True in DB

# Test 2: Idempotent revert
result2 = await revert_action_handler({"action_id": note["action_id"]}, ctx)
assert result2["success"] is False
assert result2.get("already_reverted") is True

# Test 3: update_note → revert
note = await create_note_handler(...)
update = await update_note_handler({"note_id": note["id"], "content": "new content"}, ctx)
revert = await revert_action_handler({"action_id": update["action_id"]}, ctx)
# Verify note content restored to original

# Test 4: revert_action với action_id không tồn tại
result = await revert_action_handler({"action_id": "fake-id"}, ctx)
assert result["success"] is False

# Test 5: revert_action không có action_id → lấy gần nhất
result = await revert_action_handler({}, ctx)
assert result["success"] is True

# Test 6: create_schedule → revert (kiểm tra Google Calendar warning)
sched = await create_schedule_handler({...}, ctx)
revert = await revert_action_handler({"action_id": sched["action_id"]}, ctx)
assert "Google Calendar" in revert["detail"]["message"]
```

---

*Document version: 1.0 | Prepared for Cortex Agent Backend implementation*