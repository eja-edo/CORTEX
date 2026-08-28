"""
Internal API Endpoints for Service-to-Service Communication

These endpoints are NOT exposed to the internet. They are used by internal
microservices (OCR service, LLM service) to update backend state.

Security: Protected by X-Internal-API-Key header.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.database_async import get_async_db
from app.models import Asset, AssetStatus, AttentionItemType
from app.schemas import (
    InternalTaskBatch,
    InternalTaskBatchResult,
    InternalTaskItemResult,
)
from app.services.task_ingest import TaskIngestService
from app.services.attention_gate import request_attention_sync
from app.core.internal_auth import verify_internal_key, get_internal_user, InternalUser
from app.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/internal", tags=["internal"])


class AssetStatusUpdate(BaseModel):
    """Payload for updating asset processing status."""
    status: str  # "processing" | "completed" | "failed"
    failed_reason: str | None = None


def verify_internal_key(x_internal_api_key: str = Header(..., alias="X-Internal-API-Key")):
    """Verify that the request comes from an authorized internal service."""
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_API_KEY not configured in backend",
        )
    
    if x_internal_api_key != settings.INTERNAL_API_KEY:
        logger.warning("Invalid internal API key attempt")
        raise HTTPException(
            status_code=403,
            detail="Invalid internal API key",
        )


@router.patch("/assets/{asset_id}/status")
def update_asset_status_internal(
    asset_id: UUID,
    payload: AssetStatusUpdate,
    _: None = Depends(verify_internal_key),
    db: Session = Depends(get_db),
):
    """
    Update asset processing status (called by OCR/LLM services).
    
    This endpoint allows internal microservices to update the Asset.status
    field in PostgreSQL without needing direct database access.
    
    Valid status values:
    - "processing": Asset is being processed
    - "completed": Processing finished successfully
    - "failed": Processing failed (provide failed_reason)
    """
    # Validate status value
    try:
        new_status = AssetStatus(payload.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {payload.status}. Must be one of: {[s.value for s in AssetStatus]}",
        )
    
    # Find asset
    asset = db.query(Asset).filter(Asset.id == asset_id).first()
    if not asset:
        raise HTTPException(
            status_code=404,
            detail=f"Asset {asset_id} not found",
        )
    
    # Update status
    old_status = asset.status
    asset.status = new_status
    asset.updated_at = datetime.utcnow()
    
    if payload.failed_reason:
        asset.failed_reason = payload.failed_reason
    
    db.commit()
    
    logger.info(
        f"Asset {asset_id} status updated: {old_status.value} → {new_status.value}"
        + (f" (reason: {payload.failed_reason})" if payload.failed_reason else "")
    )
    
    return {"ok": True, "asset_id": str(asset_id), "status": new_status.value}


class NotificationBlockSchema(BaseModel):
    type: str  # text, image, html, code, markdown, etc.
    text: str | None = None
    url: str | None = None
    html: str | None = None
    language: str | None = None
    content: str | None = None


class NotificationActionSchema(BaseModel):
    label: str
    action: str = "navigate"
    url: str | None = None
    payload: dict[str, Any] | None = None


class CreateNotificationRequest(BaseModel):
    user_id: str
    title: str
    body: str = ""
    type: str = "system"
    content: list[NotificationBlockSchema] = []
    actions: list[NotificationActionSchema] = []
    # Optional — present once a workflow trigger names the domain item it's
    # about (System Workflow Reference Model, 4.0, not built yet). All
    # three or none: a partial triple falls back to the pass-through branch
    # in attention_gate.py rather than erroring, since a caller mid-rollout
    # is a normal state, not a bug.
    item_type: AttentionItemType | None = None
    item_id: str | None = None
    reason_key: str | None = None


def _create_attention_request(payload: CreateNotificationRequest, db: Session) -> dict:
    try:
        user_uuid = UUID(payload.user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    item_id_uuid: UUID | None = None
    if payload.item_id is not None:
        try:
            item_id_uuid = UUID(payload.item_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid item_id format")

    notification = request_attention_sync(
        db,
        user_id=user_uuid,
        type=payload.type,
        title=payload.title,
        body=payload.body,
        content=[b.model_dump() for b in payload.content] or None,
        actions=[a.model_dump() for a in payload.actions],
        item_type=payload.item_type,
        item_id=item_id_uuid,
        reason_key=payload.reason_key,
    )

    if notification is None:
        return {"ok": True, "notification_id": None, "gated": True}
    return {"ok": True, "notification_id": str(notification.id)}


@router.post("/attention/request", include_in_schema=False)
def request_attention_internal(
    payload: CreateNotificationRequest,
    _: None = Depends(verify_internal_key),
    db: Session = Depends(get_db),
):
    """Attention Gate entry point (Milestone 4.3/6.1): called by workflow
    `action.request_attention` (and its deprecated alias
    `action.send_notification`). Today the gate is a pass-through stub —
    see `app.services.attention_gate`."""
    return _create_attention_request(payload, db)


@router.post("/notifications", include_in_schema=False)
def create_notification_internal(
    payload: CreateNotificationRequest,
    _: None = Depends(verify_internal_key),
    db: Session = Depends(get_db),
):
    """Deprecated alias for /internal/attention/request, kept for any
    caller not yet migrated. Routes through the same Attention Gate."""
    return _create_attention_request(payload, db)


@router.post("/tasks", response_model=InternalTaskBatchResult)
async def ingest_tasks_internal(
    payload: InternalTaskBatch,
    _: None = Depends(verify_internal_key),
    db: AsyncSession = Depends(get_async_db),
):
    """Bot họp đẩy action item vào — `docs/DESIGN.md` mục 9.1, tầng 1 của 1.1.

    Cortex **không tự trích xuất** action item (1.4): bot họp đã làm khâu
    đó, và cạnh tranh nó là tự chọn trận thua. Endpoint này chỉ nhận về,
    gom theo dự án, rồi giao cho tầng 3 quyết định lúc nào nói.

    **Luôn trả 200 kể cả khi có item bị bỏ qua**, và đó là chủ ý. Một người
    trong cuộc họp chưa liên kết Mezon là chuyện bình thường, không phải
    lỗi của bên gửi; trả 4xx sẽ khiến bot thử lại cả lô mãi mãi cho một
    tình huống không lần thử lại nào sửa được. Item nào không vào được thì
    nằm trong `items[].skipped_reason` để bot nói lại ở channel.

    Không có bước xác nhận: task vào thẳng `todo`. `pending_confirm` dành
    cho thứ **Cortex tự đoán** từ hội thoại — action item ở đây đã qua mắt
    người trong cuộc họp rồi, bắt xác nhận lại là bắt làm hai lần một việc.
    """
    result = await TaskIngestService(db).ingest(payload.items)

    logger.info(
        "internal task ingest: %d created, %d skipped",
        result.created_count,
        result.skipped_count,
    )
    return InternalTaskBatchResult(
        created_count=result.created_count,
        skipped_count=result.skipped_count,
        items=[
            InternalTaskItemResult(
                external_id=item.external_id,
                task_id=item.task_id,
                created=item.created,
                skipped_reason=item.skipped_reason,
            )
            for item in result.items
        ],
    )


class GateBypassUpdate(BaseModel):
    """Gán một người dùng vào nhóm A hoặc B của phép thử (DESIGN 12.2)."""

    enabled: bool


@router.patch("/users/{user_id}/gate-bypass", include_in_schema=False)
async def set_gate_bypass_internal(
    user_id: UUID,
    payload: GateBypassUpdate,
    _: None = Depends(verify_internal_key),
    db: AsyncSession = Depends(get_async_db),
):
    """Bật/tắt Attention Gate cho một người dùng — điều khiển phép thử A/B.

    **Cố ý là endpoint nội bộ, không phải một mục trong trang cài đặt.**
    Đây là biến điều khiển của một thí nghiệm, không phải một tuỳ chọn sản
    phẩm: cho người dùng thấy nó là mời họ tự đổi nhóm giữa chừng, và phép
    thử đo một thứ không còn ý nghĩa. Nó cũng không phải thứ nên tồn tại
    lâu dài — khi hai con số ở 12.3 đọc xong, cột này hết việc.
    """
    from app.models import UserPreferences

    prefs = await db.get(UserPreferences, user_id)
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
    prefs.gate_bypass = payload.enabled
    await db.commit()

    logger.info(
        "gate_bypass set to %s for user %s (A/B group %s)",
        payload.enabled,
        user_id,
        "A — nhắc ngây thơ" if payload.enabled else "B — qua Gate",
    )
    return {"user_id": str(user_id), "gate_bypass": payload.enabled}


@router.get("/health")
def internal_health_check(
    _: None = Depends(verify_internal_key),
):
    """
    Health check endpoint for internal services.
    
    Allows OCR/LLM services to verify backend is reachable and responsive.
    """
    return {
        "status": "healthy",
        "service": "backend",
        "ocr_service_mode": settings.OCR_SERVICE_MODE,
    }
