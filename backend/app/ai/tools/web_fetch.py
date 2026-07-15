"""Web fetch tool - fetch a URL and extract content as markdown.

Uses the same multi-engine extraction pipeline as render.py:
main_container -> readability -> trafilatura (optional), with
auto-fallback to Jina AI Reader when quality is poor.
"""

import asyncio

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.config import settings
from app.utils.logger import get_logger
from app.utils.web_reader import ExtractionError, Reader

logger = get_logger(__name__)


class WebFetchInput(BaseModel):
    url: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="The URL to fetch and extract content from",
    )
    timeout: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Request timeout in seconds",
    )


async def web_fetch_handler(args: dict, ctx: ToolContext) -> dict:
    url = args["url"]
    timeout = args.get("timeout", 30)
    jina_api_key = settings.JINA_API_KEY or None

    loop = asyncio.get_event_loop()
    reader = Reader(timeout=timeout, jina_api_key=jina_api_key)

    try:
        result = await loop.run_in_executor(None, reader.fetch, url)

        return {
            "url": result["url"],
            "title": result.get("title", ""),
            "markdown": result["markdown"],
            "length": result["length"],
            "method_used": result.get("method_used", ""),
            "candidate_lengths": result.get("candidate_lengths", {}),
            "last_updated": result.get("last_updated"),
            "breadcrumb": result.get("breadcrumb"),
            "quality_warning": result.get("quality_warning"),
            "quality_fallback_reason": result.get("quality_fallback_reason"),
        }

    except ExtractionError as exc:
        logger.warning("web_fetch extraction error for %s: %s", url, exc)
        return {
            "url": url,
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("web_fetch failed for %s: %s", url, exc, exc_info=True)
        return {
            "url": url,
            "error": f"Lỗi không mong đợi: {exc!r}",
        }
    finally:
        reader.close()


WEB_FETCH_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "The URL to fetch and extract content from",
        },
        "timeout": {
            "type": "integer",
            "description": "Request timeout in seconds (default: 30, max: 120)",
            "default": 30,
        },
    },
    "required": ["url"],
}


WEB_FETCH_DEFINITION = {
    "name": "web_fetch",
    "handler": web_fetch_handler,
    "input_model": WebFetchInput,
    "schema": WEB_FETCH_SCHEMA,
    "description": (
        "Fetch a URL and extract its main content as clean markdown. "
        "Supports documentation sites, blogs, and general web pages. "
        "Automatically falls back to Jina AI Reader when local extraction quality is poor. "
        "Returns title, markdown content, length, metadata (last_updated, breadcrumb), "
        "and extraction method info."
    ),
}
