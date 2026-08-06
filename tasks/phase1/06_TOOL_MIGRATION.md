# Milestone 1.6: Tool→Command Migration

**Timeline:** 4-5 ngày  
**Dependencies:** 1.5 (Command Registry)  
**Effort:** Medium-Large  

---

## 🎯 Mục tiêu

Migrate 4 mutating tools để chạy qua CommandRegistry thay vì gọi service trực tiếp:
- `create_note` → `note.create` command
- `update_note` → `note.update` command
- `create_schedule` → `schedule.create` command
- `update_schedule` → `schedule.update` command

**Nguyên tắc:**
- Tool handler becomes thin wrapper calling CommandRegistry
- Validation/permission/audit/snapshot logic moves to CommandRegistry
- Tool response format remains unchanged (backward compatibility)
- Existing tests must pass without modification

---

## 📋 Tasks

### Task 1.6.1: Implement Note Command Handlers

**Output:** `backend/app/commands/handlers/note_commands.py`

```python
"""
Note command handlers.

These are the ACTUAL implementations called by CommandRegistry.
Tool handlers (in app/ai/tools/) become thin wrappers.
"""

from uuid import UUID
from app.commands.schemas import Command
from app.commands.args import NoteCreateArgs, NoteUpdateArgs, NoteDeleteArgs
from app.ai.agents.tool_context import ToolContext
from app.services.notes import NoteService
from app.services.proposal_service import ProposalService
from app.utils.note_delta import build_text_patch
from app.schemas import NoteCreate, NoteUpdate
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def note_create_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Create note command handler.
    
    Called by CommandRegistry after validation/permission checks.
    """
    args = NoteCreateArgs(**command.args)
    
    async with ctx.async_db() as db:
        service = NoteService(db)
        
        # Create note
        note = await service.create_note(
            payload=NoteCreate(
                workspace_id=args.workspace_id,
                title=args.title,
                content=args.content,
                parent_note_id=args.parent_note_id,
                content_type=args.content_type
            ),
            user_id=ctx.user_id
        )
        
        logger.info(f"Note created: {note.id}")
        
        return {
            "id": str(note.id),
            "workspace_id": str(note.workspace_id),
            "title": note.title,
            "created_at": note.created_at.isoformat() if note.created_at else None,
            "prev_state": {"note_id": str(note.id)}  # For revert (soft delete)
        }


async def note_update_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Update note command handler.

    ⚠️ 2026-08-06: `NoteService.update_note()` áp dụng thay đổi trực tiếp
    (dùng bởi REST API PATCH /notes/{id}), nhưng khi command này được gọi
    TỪ AI (source="AI"), luồng thật đang dùng phải là tạo Proposal chờ
    duyệt (`ProposalService.create_proposal`), giống `update_note_handler`
    hiện tại trong `backend/app/ai/tools/update_note.py` — KHÔNG apply
    ngay. Handler dưới đây phản ánh đúng luồng đó thay vì update trực tiếp
    như bản gốc của milestone này. Không có `prev_state`/snapshot vì chưa
    có gì thay đổi để revert — muốn huỷ, dùng command `note.proposal.reject`.
    """
    args = NoteUpdateArgs(**command.args)

    async with ctx.async_db() as db:
        note_service = NoteService(db)
        proposal_service = ProposalService(db)

        current = await note_service.get_note(args.note_id, ctx.user_id)
        if not current:
            raise ValueError(f"Note not found: {args.note_id}")

        current_content = await note_service.materialize_note_content(current)
        if args.content is None or current_content == args.content:
            return {
                "id": str(current.id),
                "version": current.version,
                "proposal_id": None,
                "updated": False,
            }

        patch = build_text_patch(current_content, args.content)
        proposal = await proposal_service.create_proposal(
            note=current,
            user_id=ctx.user_id,
            old_content=current_content,
            new_content=args.content,
            patch=patch,
            creator_type="AGENT",
            creator_id=f"agent:{ctx.user_id}",
            conversation_id=command.conversation_id,
        )

        logger.info(f"note.update: created proposal {proposal.id} for note {current.id}")

        return {
            "id": str(current.id),
            "version": current.version,
            "proposal_id": str(proposal.id),
            "updated": False,
            # KHÔNG có "prev_state" — command này không revertable, xem docstring
        }


async def note_delete_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Delete note command handler (soft delete).
    """
    args = NoteDeleteArgs(**command.args)
    
    async with ctx.async_db() as db:
        service = NoteService(db)
        
        # Get note for snapshot
        note = await service.get_note(args.note_id, ctx.user_id)
        if not note:
            raise ValueError(f"Note not found: {args.note_id}")
        
        # Save state for potential restore
        prev_state = {
            "note_id": str(args.note_id),
            "title": note.title,
            "content": await service.materialize_note_content(note)
        }
        
        # Soft delete
        success = await service.delete_note(args.note_id, ctx.user_id)
        
        if not success:
            raise ValueError("Delete failed")
        
        logger.info(f"Note deleted: {args.note_id}")
        
        return {
            "note_id": str(args.note_id),
            "deleted": True,
            "prev_state": prev_state
        }


# Register commands with CommandRegistry
def register_note_commands():
    """Register all note commands."""
    from app.commands.registry import get_command_registry
    from app.commands.schemas import PermissionScope
    
    registry = get_command_registry()
    
    registry.register(
        name="note.create",
        description="Create a new note in workspace",
        args_schema=NoteCreateArgs,
        handler=note_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    registry.register(
        name="note.update",
        description="Propose an update to an existing note (chờ duyệt, không apply ngay)",
        args_schema=NoteUpdateArgs,
        handler=note_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=False  # tạo Proposal, không có state để revert — xem note_update_handler
    )
    
    registry.register(
        name="note.delete",
        description="Delete note (soft delete)",
        args_schema=NoteDeleteArgs,
        handler=note_delete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    logger.info("Note commands registered")
```

**Checklist:**
- [ ] `note_create_handler` implementation
- [ ] `note_update_handler` with snapshot logic
- [ ] `note_delete_handler` implementation
- [ ] `register_note_commands()` function
- [ ] prev_state returned for snapshot
- [ ] Error handling
- [ ] Documentation

---

### Task 1.6.2: Implement Schedule Command Handlers

**Output:** `backend/app/commands/handlers/schedule_commands.py`

```python
"""
Schedule command handlers.
"""

from uuid import UUID
from datetime import datetime
from app.commands.schemas import Command
from app.commands.args import ScheduleCreateArgs, ScheduleUpdateArgs, ScheduleDeleteArgs
from app.ai.agents.tool_context import ToolContext
from app.services.schedule_service import ScheduleService
from app.schemas import ScheduleCreate
from app.models import ScheduleType
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def schedule_create_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Create schedule command handler.

    ⚠️ 2026-08-06: `ScheduleService` không có phương thức `create_schedule_simple`
    (bản gốc milestone này gọi nhầm). Chữ ký thật là
    `create_schedule(self, user_id: UUID, data: ScheduleCreate)` — sửa lại dưới đây.
    """
    args = ScheduleCreateArgs(**command.args)

    # Use sync DB (ScheduleService is sync)
    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)

        # Create schedule
        schedule = service.create_schedule(
            user_id=ctx.user_id,
            data=ScheduleCreate(
                title=args.title,
                type=ScheduleType(args.schedule_type),
                start_time=args.start_time,
                end_time=args.end_time,
                location=args.location,
                description=args.description,
                recurrence=args.recurrence,
                reminders=args.reminders,
            ),
        )
        
        logger.info(f"Schedule created: {schedule.id}")
        
        return {
            "id": str(schedule.id),
            "title": schedule.title,
            "type": schedule.type.value,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat(),
            "prev_state": {"schedule_id": str(schedule.id)}  # For revert (delete)
        }


async def schedule_update_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Update schedule command handler.
    """
    args = ScheduleUpdateArgs(**command.args)
    
    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)
        
        # Get current state for snapshot
        current = service.get_schedule_by_id(args.schedule_id, ctx.user_id)
        if not current:
            raise ValueError(f"Schedule not found: {args.schedule_id}")
        
        prev_fields = {
            "schedule_id": str(args.schedule_id),
            "title": current.title,
            "start_time": current.start_time.isoformat(),
            "end_time": current.end_time.isoformat(),
            "location": current.location,
            "description": current.description,
            "is_completed": current.is_completed
        }
        
        # Update schedule
        update_data = {}
        if args.title is not None:
            update_data["title"] = args.title
        if args.start_time is not None:
            update_data["start_time"] = args.start_time
        if args.end_time is not None:
            update_data["end_time"] = args.end_time
        if args.location is not None:
            update_data["location"] = args.location
        if args.description is not None:
            update_data["description"] = args.description
        if args.is_completed is not None:
            update_data["is_completed"] = args.is_completed
        
        updated = service.update_schedule(
            schedule_id=args.schedule_id,
            user_id=ctx.user_id,
            updates=update_data
        )
        
        logger.info(f"Schedule updated: {updated.id}")
        
        return {
            "id": str(updated.id),
            "title": updated.title,
            "start_time": updated.start_time.isoformat(),
            "end_time": updated.end_time.isoformat(),
            "prev_state": prev_fields  # For revert
        }


async def schedule_delete_handler(command: Command, ctx: ToolContext) -> dict:
    """
    Delete schedule command handler.
    """
    args = ScheduleDeleteArgs(**command.args)
    
    with ctx:
        db = ctx.get_sync_db()
        service = ScheduleService(db)
        
        # Get schedule for snapshot
        schedule = service.get_schedule_by_id(args.schedule_id, ctx.user_id)
        if not schedule:
            raise ValueError(f"Schedule not found: {args.schedule_id}")
        
        prev_state = {
            "schedule_id": str(args.schedule_id),
            "title": schedule.title,
            "type": schedule.type.value,
            "start_time": schedule.start_time.isoformat(),
            "end_time": schedule.end_time.isoformat()
        }
        
        # Delete
        service.delete_schedule(args.schedule_id)
        
        logger.info(f"Schedule deleted: {args.schedule_id}")
        
        return {
            "schedule_id": str(args.schedule_id),
            "deleted": True,
            "prev_state": prev_state
        }


def register_schedule_commands():
    """Register all schedule commands."""
    from app.commands.registry import get_command_registry
    from app.commands.schemas import PermissionScope
    
    registry = get_command_registry()
    
    registry.register(
        name="schedule.create",
        description="Create a new schedule",
        args_schema=ScheduleCreateArgs,
        handler=schedule_create_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    registry.register(
        name="schedule.update",
        description="Update existing schedule",
        args_schema=ScheduleUpdateArgs,
        handler=schedule_update_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    registry.register(
        name="schedule.delete",
        description="Delete schedule",
        args_schema=ScheduleDeleteArgs,
        handler=schedule_delete_handler,
        permission_scope=PermissionScope.WRITE,
        revertable=True
    )
    
    logger.info("Schedule commands registered")
```

**Checklist:**
- [ ] `schedule_create_handler` implementation
- [ ] `schedule_update_handler` with snapshot
- [ ] `schedule_delete_handler` implementation
- [ ] `register_schedule_commands()` function
- [ ] Handle sync DB (ScheduleService uses sync session)
- [ ] prev_state for revert

---

### Task 1.6.3: Migrate Tool Handlers to Use Commands

**File:** `backend/app/ai/tools/create_note.py`

**BEFORE:**
```python
async def create_note_handler(args: dict, ctx: ToolContext) -> dict:
    """Create note - calls service directly."""
    # Direct service call + manual snapshot
    ...
```

**AFTER:**
```python
async def create_note_handler(args: dict, ctx: ToolContext) -> dict:
    """Create note - thin wrapper around command."""
    from app.commands.registry import get_command_registry
    from app.commands.schemas import Command
    
    # Build command
    command = Command(
        command_name="note.create",
        args=args,  # Will be validated by CommandRegistry
        requested_by=ctx.user_id,
        workspace_id=ctx.workspace_id,
        conversation_id=ctx.conversation_id,
        source="AI"
    )
    
    # Execute via CommandRegistry
    registry = get_command_registry()
    result = await registry.execute(command, ctx)
    
    if not result.success:
        return {"error": result.error, "success": False}
    
    # Return in tool format (backward compatible)
    return {
        "result": result.data,
        "success": True,
        "action_id": result.action_id,
        "revert_hint": result.revert_hint
    }
```

**Migrate these 4 files:**

1. **`backend/app/ai/tools/create_note.py`**
2. **`backend/app/ai/tools/update_note.py`**
3. **`backend/app/ai/tools/create_schedule.py`**
4. **`backend/app/ai/tools/update_schedule.py`**

**Checklist:**
- [ ] Migrate `create_note_handler` → calls `note.create`
- [ ] Migrate `update_note_handler` → calls `note.update`
- [ ] Migrate `create_schedule_handler` → calls `schedule.create`
- [ ] Migrate `update_schedule_handler` → calls `schedule.update`
- [ ] Remove manual snapshot creation
- [ ] Remove manual audit logging
- [ ] Maintain backward-compatible return format
- [ ] All 4 tool files updated

---

### Task 1.6.4: Update `revert_action` Tool

**File:** `backend/app/ai/tools/revert_action.py`

**BEFORE:**
```python
async def revert_action_handler(args: dict, ctx: ToolContext) -> dict:
    """Revert action - manual logic for each tool type."""
    # Fetch snapshot
    # Manual revert logic
    ...
```

**AFTER:**
```python
async def revert_action_handler(args: dict, ctx: ToolContext) -> dict:
    """Revert action - delegate to CommandRegistry."""
    from app.commands.registry import get_command_registry
    
    action_id = args["action_id"]
    
    # CommandRegistry handles all revert logic
    registry = get_command_registry()
    result = await registry.revert_command(action_id, ctx)
    
    if not result.success:
        return {"error": result.error, "success": False}
    
    return {
        "result": result.data,
        "success": True,
        "message": f"Action {action_id} reverted successfully"
    }
```

**⚠️ Điều chỉnh 2026-08-06:** Ngoài tool `revert_action_handler`, đã có sẵn **REST endpoint riêng** `POST /agent/actions/{action_id}/revert` (`backend/app/api/agent.py::revert_action`) dùng **cùng** logic revert thủ công (`_revert_create_note`, `_revert_update_note`, `_revert_create_schedule`, `_revert_update_schedule` trong `revert_action.py`). Nếu chỉ migrate tool mà bỏ sót endpoint này, sẽ tồn tại 2 đường revert khác nhau (1 qua `CommandRegistry.revert_command()` mới, 1 qua logic cũ) — dễ drift và khó bảo trì. Endpoint REST phải được sửa để gọi `CommandRegistry.revert_command()` trong cùng lần migrate này.

**Checklist:**
- [ ] Simplify `revert_action_handler` to call CommandRegistry
- [ ] Remove manual revert logic
- [ ] **Migrate `backend/app/api/agent.py::revert_action` (REST endpoint) sang gọi `CommandRegistry.revert_command()` — không để 2 đường revert song song**
- [ ] Test revert cho note.create/note.delete/schedule.create/schedule.update/schedule.delete qua CommandRegistry (note.update không revertable — xem 05_COMMAND_REGISTRY.md)
- [ ] Test revert qua cả tool lẫn REST endpoint đều dùng chung 1 code path

---

### Task 1.6.5: Register Commands at Startup

**File:** `backend/app/__init__.py`

```python
from app.commands.handlers.note_commands import register_note_commands
from app.commands.handlers.schedule_commands import register_schedule_commands

def create_app() -> FastAPI:
    app = FastAPI(...)
    
    # ... existing setup ...
    
    # Register commands (Phase 1)
    logger.info("Registering commands...")
    register_note_commands()
    register_schedule_commands()
    logger.info("Commands registered successfully")
    
    return app
```

**Checklist:**
- [ ] Call command registration at app startup
- [ ] Verify commands registered before any requests
- [ ] Log registration success
- [ ] Handle registration errors gracefully

---

### Task 1.6.6: Regression Testing

Run existing test suite to verify no breakage:

```bash
cd backend
pytest tests/integration/test_agent_*.py -v
pytest tests/e2e/test_e2e_conversation.py -v
```

**Expected:** All tests pass without modification

**Checklist:**
- [ ] Run existing integration tests
- [ ] All tests pass
- [ ] No changes to test code required
- [ ] Tool response format unchanged
- [ ] Chat streaming still works
- [ ] Undo/revert still works
- [ ] No performance regression

---

### Task 1.6.7: Verify No Direct DB Access from Tools

**Goal:** Ensure AI cannot bypass CommandRegistry

**Script:** `backend/scripts/verify_tool_migration.py`

```python
"""
Verify that mutating tools go through CommandRegistry.
"""

import ast
import os
from pathlib import Path

def check_tool_file(file_path: Path) -> list[str]:
    """Check if tool file has direct service calls."""
    issues = []
    
    with open(file_path) as f:
        content = f.read()
    
    # Parse AST
    tree = ast.parse(content)
    
    # Look for direct service instantiation
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                # Check for NoteService(), ScheduleService()
                if node.func.id in ['NoteService', 'ScheduleService']:
                    issues.append(f"Direct service instantiation: {node.func.id}")
    
    return issues

def main():
    tools_dir = Path("backend/app/ai/tools")
    mutating_tools = [
        "create_note.py",
        "update_note.py",
        "create_schedule.py",
        "update_schedule.py"
    ]
    
    all_clear = True
    
    for tool_file in mutating_tools:
        file_path = tools_dir / tool_file
        if not file_path.exists():
            print(f"❌ File not found: {tool_file}")
            all_clear = False
            continue
        
        issues = check_tool_file(file_path)
        
        if issues:
            print(f"❌ {tool_file}:")
            for issue in issues:
                print(f"   - {issue}")
            all_clear = False
        else:
            print(f"✅ {tool_file}: OK (uses CommandRegistry)")
    
    if all_clear:
        print("\n✅ All mutating tools use CommandRegistry")
        return 0
    else:
        print("\n❌ Some tools still have direct DB access")
        return 1

if __name__ == "__main__":
    exit(main())
```

Run verification:
```bash
python backend/scripts/verify_tool_migration.py
```

**Checklist:**
- [ ] Create verification script
- [ ] Run script
- [ ] All mutating tools use CommandRegistry
- [ ] No direct service calls in tool handlers
- [ ] Read-only tools can still call services directly

---

## ✅ Milestone 1.6 Definition of Done

- [x] Note command handlers implemented (create/update[proposal]/delete) — `backend/app/commands/handlers/note_commands.py`
- [x] Schedule command handlers implemented (create/update/delete) — `backend/app/commands/handlers/schedule_commands.py`, gồm cả Google Calendar sync enqueue mà tool gốc vẫn làm
- [x] 4 tool handlers migrated to use CommandRegistry (`create_note`, `update_note`, `create_schedule`, `update_schedule`)
- [x] `revert_action` tool simplified — delegate 100% cho `CommandRegistry.revert_command()`
- [x] `backend/app/api/agent.py::revert_action` (REST endpoint) migrated sang cùng code path với tool — verified bằng test gọi cả 2 và so sánh kết quả
- [x] Commands registered on import — theo đúng convention có sẵn của `ToolRegistry` (auto-register tại module import, KHÔNG phải factory `create_app()` như plan gốc giả định — codebase này không có factory pattern)
- [x] Regression tests pass — 135/135 test mới + cũ (integration/unit/load), 7 lỗi pre-existing không liên quan giữ nguyên
- [x] No direct DB access from mutating tools — `backend/scripts/verify_tool_migration.py`, cả 4 tool pass
- [x] Backward compatibility maintained — response shape của cả 4 tool giữ nguyên chính xác (kể cả các bất đối xứng có sẵn: `update_schedule` lộ `prev_fields` ra ngoài, `create_note`/`create_schedule` thì không)
- [x] Tool response format unchanged
- [x] Performance: no significant overhead (kế thừa từ benchmark Milestone 1.5, <1ms)

**Status: hoàn thành 2026-08-06.**

### Sai lệch so với plan gốc (phát hiện khi đọc code thật)
- **`create_note` tool thật KHÔNG nhận `title`/`workspace_id`/`parent_note_id`/`content_type` từ LLM** — chỉ có `content` + `style_color`; `workspace_id` lấy từ `ctx.workspace_id`, title tự suy ra từ nội dung. `NoteCreateArgs` thiếu field `style` (tool gốc set `style={"color": style_color}`) — đã bổ sung, nếu không sẽ mất tính năng chọn màu note khi migrate.
- **`create_schedule` tool thật có side-effect Google Calendar sync** (`_enqueue_google_sync`) không nằm trong `ScheduleService.create_schedule()` — đã đưa vào `schedule_create_handler` để mọi caller của `schedule.create` (không chỉ tool này) đều được sync, thay vì chỉ ở tool wrapper.
- **`update_schedule` tool thật KHÔNG gọi Google sync** (bất đối xứng có sẵn so với create) và KHÔNG hỗ trợ `location` — giữ nguyên, không "sửa" thành nhất quán vì ngoài phạm vi.
- **Response shape của mỗi tool khác nhau, không theo 1 khuôn chung**: `create_note`/`create_schedule` không lộ `prev_state` ra ngoài, nhưng `update_schedule` LỘ `prev_fields` (hành vi có sẵn, giữ nguyên) — phải strip `prev_state` (key CommandRegistry dùng nội bộ) khỏi response của tool nhưng giữ `prev_fields` (key khác, cùng data, để tương thích ngược).
- **`note.update` không cần permission workspace-role** (tool gốc không check quyền workspace, chỉ check ownership qua `user_id`) — Command không gắn `workspace_id` để CommandRegistry rơi vào nhánh ownership-only, không vô tình siết chặt quyền hơn trước.
- **Backend không có `create_app()` factory** như plan Task 1.6.5 giả định — dùng đúng pattern auto-register-on-import có sẵn (`app/ai/tools/__init__.py`). `CommandRegistry.register()` raise lỗi khi đăng ký trùng (khác `ToolRegistry.register()` cho phép ghi đè) — gọi `register_all_commands()` 2 lần sẽ crash, chỉ import module là đủ để trigger.
- **`note.delete`/`schedule.delete` được đăng ký `revertable=True` nhưng `_default_revert` (Milestone 1.5) chưa có nhánh xử lý** — đã bổ sung (un-delete cho note, recreate-from-snapshot cho schedule vì là hard delete) để không "claim khống" khả năng revert.
- Test `test_command_registry.py`'s fixture gọi `reset_command_registry()` (global singleton) mỗi test — vô tình xoá luôn registration thật mà tool handlers cần khi chạy chung 1 pytest session với `test_tool_command_migration.py`. Sửa fixture dùng `CommandRegistry()` cục bộ, không đụng singleton global.

---

## 🧪 Testing Strategy

### 1. Unit Tests (Command Handlers)

```bash
pytest tests/unit/test_note_commands.py -v
pytest tests/unit/test_schedule_commands.py -v
```

### 2. Integration Tests (Tool→Command Flow)

```bash
pytest tests/integration/test_tool_command_migration.py -v
```

### 3. E2E Tests (Chat Flow)

```bash
pytest tests/e2e/test_e2e_conversation.py -v
```

### 4. Regression Tests

```bash
# Run ALL existing tests
pytest tests/ -v --tb=short
```

---

## 📊 Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| Tests pass | 100% | `pytest tests/` |
| Performance overhead | < 50ms | Compare tool execution time before/after |
| Code coverage | > 80% | `pytest --cov=app/commands` |
| No regressions | 0 | Existing tests must pass |

---

**Next Milestone:** [1.7 Context Service](07_CONTEXT_SERVICE.md)
