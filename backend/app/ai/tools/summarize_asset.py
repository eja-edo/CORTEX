"""Summarize asset tool."""

from pydantic import BaseModel, Field
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, AssetStatus
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SummarizeAssetInput(BaseModel):
    """Validation model for summarize_asset tool."""
    asset_id: str = Field(..., description="Asset UUID to summarize")


async def summarize_asset_handler(args: dict, ctx: ToolContext) -> dict:
    """
    Get AI-generated summary and knowledge timeline for an asset.
    
    Security:
    - User must own the asset or have workspace access
    """
    try:
        asset_id = UUID(args["asset_id"])
    except ValueError:
        raise ValueError(f"Invalid asset_id format: {args['asset_id']}")

    try:
        async with ctx.async_db() as db:
            # Get asset (must own it)
            stmt = select(Asset).where(
                Asset.id == asset_id,
                Asset.user_id == ctx.user_id,
            )
            result = await db.execute(stmt)
            asset = result.scalar_one_or_none()

            if not asset:
                raise ValueError("Asset not found or you don't have permission")

            # Return asset info
            # Note: In production, this would fetch the AssetKnowledgeSummary from MongoDB
            return {
                "id": str(asset.id),
                "title": asset.title or "Untitled",
                "type": asset.type.value,
                "status": asset.status.value,
                "description": asset.description,
                "duration_ms": asset.duration_ms,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "processed_at": asset.processed_at.isoformat() if asset.processed_at else None,
                "summary": "Awaiting processing..." if asset.status != AssetStatus.COMPLETED else asset.description or "No summary available",
            }

    except Exception as exc:
        logger.error(f"summarize_asset failed: {exc}", exc_info=True)
        raise


SUMMARIZE_ASSET_SCHEMA = {
    "type": "object",
    "properties": {
        "asset_id": {
            "type": "string",
            "description": "UUID of the asset to summarize",
        },
    },
    "required": ["asset_id"],
}

SUMMARIZE_ASSET_DEFINITION = {
    "name": "summarize_asset",
    "handler": summarize_asset_handler,
    "input_model": SummarizeAssetInput,
    "schema": SUMMARIZE_ASSET_SCHEMA,
    "description": "Get summary and knowledge timeline for a recorded session (video/audio).",
}
