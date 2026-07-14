"""Web search tool using UnSearch."""

from typing import Optional

import httpx
from pydantic import BaseModel, Field

from app.config import settings
from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class WebSearchInput(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=5, ge=1, le=20)


async def web_search_handler(args: dict, ctx: ToolContext) -> dict:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{settings.UNSEARCH_URL}/api/v1/search/",
                headers={
                    "Content-Type": "application/json",
                },
                json={
                    "query": args["query"],
                    "max_results": args.get("max_results", 5),
                },
            )

            response.raise_for_status()

            data = response.json()

            return {
                "query": args["query"],
                "total_results": data.get("total_results", 0),
                "results": [
                    {
                        "title": result.get("title"),
                        "url": result.get("url"),
                        "snippet": result.get("snippet"),
                        "score": result.get("score"),
                    }
                    for result in data.get("results", [])
                ],
            }

    except Exception as exc:
        logger.error("web_search failed: %s", exc, exc_info=True)
        raise


WEB_SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search query",
        },
        "max_results": {
            "type": "integer",
            "description": "Maximum number of results",
            "default": 5,
        },
    },
    "required": ["query"],
}


WEB_SEARCH_DEFINITION = {
    "name": "web_search",
    "handler": web_search_handler,
    "input_model": WebSearchInput,
    "schema": WEB_SEARCH_SCHEMA,
    "description": "Search the web for recent information using UnSearch.",
}