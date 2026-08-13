from fastapi import APIRouter, Request, HTTPException, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import hashlib
import json

from app.database import get_db
from app.models.workflow import WorkflowTriggerWebhook, WorkflowDefinition, WorkflowStatus

router = APIRouter()


@router.post("/{webhook_path}", status_code=status.HTTP_202_ACCEPTED)
async def receive_webhook(
    webhook_path: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(WorkflowTriggerWebhook).where(
            WorkflowTriggerWebhook.webhook_path == webhook_path,
            WorkflowTriggerWebhook.is_active == True
        )
    )
    webhook = result.scalar_one_or_none()

    if not webhook:
        raise HTTPException(status_code=404, detail="Webhook not found")

    secret_header = request.headers.get("X-Webhook-Secret")
    if not secret_header:
        raise HTTPException(status_code=401, detail="Missing webhook secret")
    provided_hash = hashlib.sha256(secret_header.encode()).hexdigest()
    if provided_hash != webhook.secret_hash:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    result = await db.execute(
        select(WorkflowDefinition).where(
            WorkflowDefinition.id == webhook.workflow_id,
            WorkflowDefinition.status == WorkflowStatus.ACTIVE
        )
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(status_code=409, detail="Workflow is not active")

    body = await request.body()
    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {"raw": body.decode()}

    trigger_data = {
        "event": "webhook.received",
        "webhook_path": webhook_path,
        "headers": dict(request.headers),
        "payload": payload,
    }

    from app.temporal.client import start_workflow_execution

    instance_id = await start_workflow_execution(workflow, trigger_data)
    print(
        f"[WebhookTrigger] Triggered workflow {workflow.id} "
        f"instance={instance_id}"
    )

    return {
        "status": "accepted",
        "workflow_id": str(workflow.id),
        "instance_id": instance_id,
    }
