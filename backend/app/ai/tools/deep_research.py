"""Deep research tool using UnSearch agent research endpoint."""

from typing import List, Optional

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DeepResearchInput(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    depth: str = Field(
        default="moderate",
        pattern="^(basic|moderate|comprehensive)$",
    )
    focus_areas: Optional[List[str]] = None


async def deep_research_handler(args: dict, ctx: ToolContext) -> dict:
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.UNSEARCH_URL}/api/v1/agent/research",
                headers={
                    "Content-Type": "application/json",
                },
                json={
                    "query": args["topic"],
                    "depth": args.get("depth", "moderate"),
                    "focus_areas": args.get("focus_areas", []),
                },
            )

            response.raise_for_status()

            data = response.json()

            return {
                "topic": args["topic"],
                "summary": data.get("summary"),
                "findings": data.get("findings"),
                "sources": data.get("sources"),
                "metadata": data.get("metadata", {}),
            }

    except Exception as exc:
        logger.error("deep_research failed: %s", exc, exc_info=True)
        raise


DEEP_RESEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {
            "type": "string",
            "description": "Research topic",
        },
        "depth": {
            "type": "string",
            "enum": ["basic", "moderate", "comprehensive"],
            "description": "Research depth",
        },
        "focus_areas": {
            "type": "array",
            "items": {
                "type": "string",
            },
            "description": "Optional focus areas",
        },
    },
    "required": ["topic"],
}


DEEP_RESEARCH_DEFINITION = {
    "name": "deep_research",
    "handler": deep_research_handler,
    "input_model": DeepResearchInput,
    "schema": DEEP_RESEARCH_SCHEMA,
    "description": "Perform multi-step deep research on a topic using UnSearch research agent.",
}