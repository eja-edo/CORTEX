"""Export and erase one customer's data (WP43; DESIGN §6). Owner only: erasing personal data is a decision with legal weight, not a
button for the whole team. The line it leaves in the activity log names no one: only the internal id and how many rows changed."""
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from cortex_leads.console.auth import Session, need
from cortex_leads.console.trail import audit
from cortex_leads.db.session import tenant_session
from cortex_leads.privacy.erase import NOT_REACHED, EraseBlocked, erase_customer, export_customer

router = APIRouter(prefix="/customers")


@router.get("/{conversation_id}/export")
async def export(conversation_id: UUID, sess: Session = need("settings.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            data = await export_customer(s, conversation_id)
        except LookupError:
            raise HTTPException(404, "conversation not found") from None
        await audit(sess, s, "data", "customer.exported", "Xuất dữ liệu của một khách", obj=("conversation", str(conversation_id), None),
                    metadata={"messages": len(data["messages"])})
    return data


class Erase(BaseModel):
    confirm: Literal[True]  # the screen asks first; the server wants it said


@router.post("/{conversation_id}/erase")
async def erase(conversation_id: UUID, body: Erase, sess: Session = need("settings.manage")) -> dict[str, Any]:
    async with tenant_session(sess.caller.tenant_id) as s:
        try:
            counts = await erase_customer(s, conversation_id, datetime.now(UTC))
        except LookupError:
            raise HTTPException(404, "conversation not found") from None
        except EraseBlocked:
            raise HTTPException(409, {"code": "PENDING_WORK", "message": "Một tin nhắn cho khách này đang được gửi đi. Hãy đợi vài giây rồi xoá lại."}) from None
        await audit(sess, s, "data", "customer.erased", "Xoá dữ liệu cá nhân của một khách", obj=("conversation", str(conversation_id), None), metadata=counts)
    return {"erased": counts, "not_reached": NOT_REACHED}
