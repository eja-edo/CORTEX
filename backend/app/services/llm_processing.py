"""
LLM Processing Service — Gemini API Integration
"""

import json
from dataclasses import dataclass
from typing import Any, Optional

import google.generativeai as genai
from google.generativeai import protos

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class LLMResult:
    success: bool
    tokens_used: int = 0
    cost_usd: float = 0.0
    error_message: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None


# ── Schema definitions cho Gemini (dùng protos.Schema thay Pydantic) ──────────

def _screen_segment_schema() -> protos.Schema:
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "screen_type": protos.Schema(
                type=protos.Type.STRING,
                enum=["browser", "editor", "terminal", "settings", "other"],
            ),
            "application": protos.Schema(type=protos.Type.STRING),
            "user_intent": protos.Schema(type=protos.Type.STRING),
            "knowledge_value": protos.Schema(
                type=protos.Type.NUMBER,
                description="0.0 = no value, 1.0 = critical learning moment",
            ),
            "summary": protos.Schema(type=protos.Type.STRING),
            "topics": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            "entities": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "type": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["url", "code", "error"],
                        ),
                        "value": protos.Schema(type=protos.Type.STRING),
                        "confidence": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["type", "value", "confidence"],
                ),
            ),
            "searchable_keywords": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
        },
        required=["screen_type", "user_intent", "knowledge_value", "summary",
                  "topics", "searchable_keywords"],
    )


def _knowledge_extraction_schema() -> protos.Schema:
    confidence_field = protos.Schema(type=protos.Type.NUMBER)
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "facts": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "content": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                        "context": protos.Schema(type=protos.Type.STRING),
                    },
                    required=["content", "confidence"],
                ),
            ),
            "errors": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "message": protos.Schema(type=protos.Type.STRING),
                        "error_type": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["connection", "syntax", "runtime"],
                        ),
                        "resolution": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                    },
                    required=["message", "resolution", "confidence"],
                ),
            ),
            "code_patterns": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "snippet": protos.Schema(type=protos.Type.STRING),
                        "language": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["python", "javascript", "bash", "sql"],
                        ),
                        "purpose": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                    },
                    required=["snippet", "language", "purpose", "confidence"],
                ),
            ),
            "commands": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "command": protos.Schema(type=protos.Type.STRING),
                        "platform": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["docker", "bash", "powershell"],
                        ),
                        "purpose": protos.Schema(type=protos.Type.STRING),
                    },
                    required=["command", "platform", "purpose"],
                ),
            ),
        },
    )


def _session_synthesis_schema() -> protos.Schema:
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "session_title": protos.Schema(type=protos.Type.STRING),
            "primary_technology": protos.Schema(type=protos.Type.STRING),
            "difficulty_level": protos.Schema(
                type=protos.Type.STRING,
                enum=["beginner", "intermediate", "advanced"],
            ),
            "overall_summary": protos.Schema(type=protos.Type.STRING),
            "tags": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            "workflow": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "step": protos.Schema(type=protos.Type.INTEGER),
                        "description": protos.Schema(type=protos.Type.STRING),
                    },
                    required=["step", "description"],
                ),
            ),
            "problems_encountered": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "problem": protos.Schema(type=protos.Type.STRING),
                        "context": protos.Schema(type=protos.Type.STRING),
                        "resolution": protos.Schema(type=protos.Type.STRING),
                    },
                    required=["problem"],
                ),
            ),
            "solutions_found": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "problem": protos.Schema(type=protos.Type.STRING),
                        "solution": protos.Schema(type=protos.Type.STRING),
                        "generalizability": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["problem", "solution"],
                ),
            ),
            "knowledge_gained": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
        },
        required=["session_title", "difficulty_level", "overall_summary", "tags"],
    )


class GeminiProcessingService:
    """Service for Gemini API-based LLM processing."""

    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY
        self.DEFAULT_MODEL = settings.GEMINI_DEFAULT_MODEL
        self.SYNTHESIS_MODEL = settings.GEMINI_SYNTHESIS_MODEL

        if self.api_key:
            genai.configure(api_key=self.api_key)

    async def process_screen_segments(
        self,
        raw_text: str,
        start_ms: int,
        end_ms: int,
        asset_context: str = "",
    ) -> LLMResult:
        """Process OCR text from a screen window using Gemini (async)."""
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        if not raw_text or not raw_text.strip():
            return LLMResult(
                success=True,
                parsed_data={
                    "screen_type": None,
                    "application": None,
                    "user_intent": None,
                    "knowledge_value": 0.0,
                    "summary": "Empty screen",
                    "topics": [],
                    "entities": [],
                    "searchable_keywords": [],
                },
            )

        prompt = f"""Analyze this OCR text from a screen recording \
(timestamp {start_ms}ms - {end_ms}ms, asset: {asset_context}).

OCR TEXT:
{raw_text}

Focus on:
- Detecting screen content type
- Understanding user workflows
- Identifying errors, code patterns, commands
- Knowledge value: 0 = screenshot only, 1 = critical learning moment
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    top_p=0.8,
                    top_k=40,
                    max_output_tokens=800,
                    response_mime_type="application/json",
                    response_schema=_screen_segment_schema(),
                ),
            )

            parsed = json.loads(response.text)

            # Lấy token count chính xác từ API
            usage = response.usage_metadata
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = prompt_tokens + output_tokens

            # Gemini 2.5 Flash pricing (update nếu dùng model khác)
            cost = (prompt_tokens * 0.075 + output_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Gemini screen analysis failed: {e}")
            return LLMResult(success=False, error_message=str(e))

    async def extract_knowledge(self, text: str, context: str = "") -> LLMResult:
        """Extract structured knowledge from OCR text (async)."""
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        prompt = f"""Extract structured knowledge from this OCR text\
{' (' + context + ')' if context else ''}.

TEXT:
{text}

Extract facts, errors, code patterns, and commands found in the text.
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=1000,
                    response_mime_type="application/json",
                    response_schema=_knowledge_extraction_schema(),
                ),
            )

            parsed = json.loads(response.text)
            usage = response.usage_metadata
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = prompt_tokens + output_tokens
            cost = (prompt_tokens * 0.075 + output_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Knowledge extraction failed: {e}")
            return LLMResult(success=False, error_message=str(e))

    async def synthesize_session(
        self,
        processed_segments: list[dict],
        asset_title: str = "",
        duration_ms: int = 0,
    ) -> LLMResult:
        """Synthesize session-level summary (async)."""
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        segments_summary = "\n".join(
            f"[{s.get('start_ms')}ms] {s.get('summary', 'N/A')} "
            f"(type: {s.get('screen_type')}, value: {s.get('knowledge_value')})"
            for s in processed_segments[:20]
        )

        prompt = f"""Synthesize a high-level session summary from this screen recording \
(asset: {asset_title}, duration: {duration_ms}ms).

SEGMENTS ({len(processed_segments)} total):
{segments_summary}

Analyze the workflow, identify problems, solutions, and key learning moments.
"""

        try:
            model = genai.GenerativeModel(self.SYNTHESIS_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.5,
                    max_output_tokens=1500,
                    response_mime_type="application/json",
                    response_schema=_session_synthesis_schema(),
                ),
            )

            parsed = json.loads(response.text)
            usage = response.usage_metadata
            prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
            output_tokens = getattr(usage, "candidates_token_count", 0) or 0
            total_tokens = prompt_tokens + output_tokens
            cost = (prompt_tokens * 0.075 + output_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Session synthesis failed: {e}")
            return LLMResult(success=False, error_message=str(e))


gemini_service = GeminiProcessingService()