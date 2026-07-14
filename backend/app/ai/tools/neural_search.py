"""Semantic / neural search tool using UnSearch."""

from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class NeuralSearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    num_results: int = Field(default=5, ge=1, le=20)
    use_autoprompt: bool = Field(default=True)


async def neural_search_handler(args: dict, ctx: ToolContext) -> dict:
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(
                f"{settings.UNSEARCH_URL}/api/v1/neural/search",
                headers={
                    "Content-Type": "application/json",
                },
                json={
                    "query": args["query"],
                    "num_results": args.get("num_results", 5),
                    "use_autoprompt": args.get("use_autoprompt", True),
                },
            )

            response.raise_for_status()

            data = response.json()

            return {
                "query": args["query"],
                "results": data.get("results", []),
                "metadata": data.get("search_metadata", {}),
            }

    except Exception as exc:
        logger.error("neural_search failed: %s", exc, exc_info=True)
        raise


NEURAL_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Semantic search query",
        },
        "num_results": {
            "type": "integer",
            "description": "Maximum number of results",
            "default": 5,
        },
        "use_autoprompt": {
            "type": "boolean",
            "description": "Enable query enhancement",
            "default": True,
        },
    },
    "required": ["query"],
}


NEURAL_SEARCH_DEFINITION = {
    "name": "neural_search",
    "handler": neural_search_handler,
    "input_model": NeuralSearchInput,
    "schema": NEURAL_SEARCH_SCHEMA,
    "description": "Perform semantic / embedding-based web search using UnSearch.",
}