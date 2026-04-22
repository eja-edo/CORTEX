"""
LLM Processing Service — Gemini API Integration

Now supports combined OCR + transcript input and produces timeline-based
knowledge output where every insight is anchored to a specific time range.
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


# ── Schema definitions ────────────────────────────────────────────────────────

def _entity_schema() -> protos.Schema:
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "type": protos.Schema(
                type=protos.Type.STRING,
                enum=["url", "code", "error", "person", "tool", "file"],
            ),
            "value": protos.Schema(type=protos.Type.STRING),
            "confidence": protos.Schema(type=protos.Type.NUMBER),
        },
        required=["type", "value", "confidence"],
    )


def _timeline_event_schema(start_sec: float, end_sec: float) -> protos.Schema:
    """Schema for a single timeline event within a window."""
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            "start_sec": protos.Schema(
                type=protos.Type.NUMBER,
                description=f"Start time in seconds. Must be >= {start_sec:.1f}",
            ),
            "end_sec": protos.Schema(
                type=protos.Type.NUMBER,
                description=f"End time in seconds. Must be <= {end_sec:.1f}",
            ),
            "activity_summary": protos.Schema(
                type=protos.Type.STRING,
                description="One concise sentence describing what happened at this moment",
            ),
            "spoken_content": protos.Schema(
                type=protos.Type.STRING,
                description="Key excerpt from speech/transcript at this moment (if available)",
            ),
            "screen_content": protos.Schema(
                type=protos.Type.STRING,
                description="Key text or UI elements visible on screen (if available)",
            ),
            "screen_type": protos.Schema(
                type=protos.Type.STRING,
                enum=["browser", "editor", "terminal", "settings", "document", "other"],
            ),
            "application": protos.Schema(type=protos.Type.STRING),
            "event_type": protos.Schema(
                type=protos.Type.STRING,
                enum=["activity", "error", "solution", "decision", "explanation"],
            ),
            "knowledge_value": protos.Schema(
                type=protos.Type.NUMBER,
                description="0.0 = trivial, 1.0 = critical learning moment",
            ),
            "topics": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            "entities": protos.Schema(
                type=protos.Type.ARRAY,
                items=_entity_schema(),
            ),
            "keywords": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
        },
        required=[
            "start_sec", "end_sec", "activity_summary",
            "event_type", "knowledge_value", "topics", "keywords",
        ],
    )


def _window_analysis_schema(start_sec: float, end_sec: float) -> protos.Schema:
    """
    Schema for a combined OCR+transcript window analysis.
    Returns both a high-level summary AND fine-grained timeline events.
    """
    return protos.Schema(
        type=protos.Type.OBJECT,
        properties={
            # High-level window summary
            "screen_type": protos.Schema(
                type=protos.Type.STRING,
                enum=["browser", "editor", "terminal", "settings", "document", "other"],
            ),
            "application": protos.Schema(type=protos.Type.STRING),
            "user_intent": protos.Schema(
                type=protos.Type.STRING,
                description="Overall user intent for this window",
            ),
            "knowledge_value": protos.Schema(
                type=protos.Type.NUMBER,
                description="Overall knowledge value 0.0-1.0 for this window",
            ),
            "summary": protos.Schema(
                type=protos.Type.STRING,
                description="2-3 sentence summary of what happened in this window",
            ),
            "topics": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            "entities": protos.Schema(
                type=protos.Type.ARRAY,
                items=_entity_schema(),
            ),
            "searchable_keywords": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            # Fine-grained timeline events within this window
            "timeline_events": protos.Schema(
                type=protos.Type.ARRAY,
                description="List of distinct events/moments within this time window, ordered by start_sec",
                items=_timeline_event_schema(start_sec, end_sec),
            ),
        },
        required=[
            "knowledge_value", "summary", "topics", "searchable_keywords",
            "timeline_events",
        ],
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
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["content", "confidence", "start_sec", "end_sec"],
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
                            enum=["connection", "syntax", "runtime", "logic", "other"],
                        ),
                        "resolution": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["message", "resolution", "confidence", "start_sec", "end_sec"],
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
                            enum=["python", "javascript", "typescript", "bash", "sql", "other"],
                        ),
                        "purpose": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["snippet", "language", "purpose", "confidence", "start_sec", "end_sec"],
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
                            enum=["docker", "bash", "powershell", "npm", "pip", "git", "other"],
                        ),
                        "purpose": protos.Schema(type=protos.Type.STRING),
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["command", "platform", "purpose", "start_sec", "end_sec"],
                ),
            ),
            "explanations": protos.Schema(
                type=protos.Type.ARRAY,
                description="Key explanations or teaching moments from the transcript",
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "topic": protos.Schema(type=protos.Type.STRING),
                        "explanation": protos.Schema(type=protos.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["topic", "explanation", "confidence", "start_sec", "end_sec"],
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
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["step", "description", "start_sec", "end_sec"],
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
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["problem", "start_sec", "end_sec"],
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
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                    },
                    required=["problem", "solution", "start_sec", "end_sec"],
                ),
            ),
            "knowledge_gained": protos.Schema(
                type=protos.Type.ARRAY,
                items=protos.Schema(type=protos.Type.STRING),
            ),
            # Full ordered knowledge timeline across the entire session
            "knowledge_timeline": protos.Schema(
                type=protos.Type.ARRAY,
                description=(
                    "Complete ordered timeline of notable moments across the whole session. "
                    "Each entry is anchored to start_sec/end_sec."
                ),
                items=protos.Schema(
                    type=protos.Type.OBJECT,
                    properties={
                        "start_sec": protos.Schema(type=protos.Type.NUMBER),
                        "end_sec": protos.Schema(type=protos.Type.NUMBER),
                        "activity_summary": protos.Schema(type=protos.Type.STRING),
                        "spoken_content": protos.Schema(type=protos.Type.STRING),
                        "screen_content": protos.Schema(type=protos.Type.STRING),
                        "screen_type": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["browser", "editor", "terminal", "settings", "document", "other"],
                        ),
                        "application": protos.Schema(type=protos.Type.STRING),
                        "event_type": protos.Schema(
                            type=protos.Type.STRING,
                            enum=["activity", "error", "solution", "decision", "explanation"],
                        ),
                        "knowledge_value": protos.Schema(type=protos.Type.NUMBER),
                        "topics": protos.Schema(
                            type=protos.Type.ARRAY,
                            items=protos.Schema(type=protos.Type.STRING),
                        ),
                        "keywords": protos.Schema(
                            type=protos.Type.ARRAY,
                            items=protos.Schema(type=protos.Type.STRING),
                        ),
                    },
                    required=["start_sec", "end_sec", "activity_summary", "event_type", "knowledge_value"],
                ),
            ),
        },
        required=["session_title", "difficulty_level", "overall_summary", "tags", "knowledge_timeline"],
    )


# ── Prompt helpers ────────────────────────────────────────────────────────────

def _format_transcript_block(transcript_text: str) -> str:
    if not transcript_text or not transcript_text.strip():
        return ""
    return f"\n\nSPEECH TRANSCRIPT:\n{transcript_text.strip()}"


def _format_ocr_block(ocr_text: str) -> str:
    if not ocr_text or not ocr_text.strip():
        return ""
    return f"\n\nSCREEN CONTENT (OCR):\n{ocr_text.strip()}"


class GeminiProcessingService:
    """Service for Gemini API-based LLM processing."""

    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY
        self.DEFAULT_MODEL = settings.GEMINI_DEFAULT_MODEL
        self.SYNTHESIS_MODEL = settings.GEMINI_SYNTHESIS_MODEL

        if self.api_key:
            genai.configure(api_key=self.api_key)

    async def process_window(
        self,
        start_sec: float,
        end_sec: float,
        ocr_text: str = "",
        transcript_text: str = "",
        asset_context: str = "",
    ) -> LLMResult:
        """
        Process a combined OCR + transcript window.

        Works for three cases:
          1. OCR only (video without speech)
          2. Transcript only (audio-only asset)
          3. Both OCR and transcript (video with speech)

        Returns timeline_events in addition to the flat summary fields.
        """
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        has_ocr = bool(ocr_text and ocr_text.strip())
        has_transcript = bool(transcript_text and transcript_text.strip())

        if not has_ocr and not has_transcript:
            return LLMResult(
                success=True,
                parsed_data={
                    "screen_type": None,
                    "application": None,
                    "user_intent": None,
                    "knowledge_value": 0.0,
                    "summary": "No content available for this window",
                    "topics": [],
                    "entities": [],
                    "searchable_keywords": [],
                    "timeline_events": [],
                },
            )

        # Build context description
        if has_ocr and has_transcript:
            content_desc = "screen recording with audio narration"
        elif has_transcript:
            content_desc = "audio recording (no screen content)"
        else:
            content_desc = "screen recording (no audio)"

        ocr_block = _format_ocr_block(ocr_text)
        transcript_block = _format_transcript_block(transcript_text)

        prompt = f"""Analyze this {content_desc} segment (timestamp {start_sec:.1f}s - {end_sec:.1f}s, asset: {asset_context}).
{ocr_block}{transcript_block}

Your task:
1. Write a concise 2-3 sentence summary of what happened in this window.
2. Identify the overall user intent and key topics.
3. Break this window into fine-grained timeline_events — each event must have:
   - start_sec / end_sec (within {start_sec:.1f}s - {end_sec:.1f}s)
   - activity_summary: one sentence describing this specific moment
   - spoken_content: relevant speech excerpt (if transcript available)
   - screen_content: key text/UI visible on screen (if OCR available)
   - event_type: activity | error | solution | decision | explanation
   - knowledge_value: 0.0 (trivial) to 1.0 (critical learning moment)

Guidelines:
- Errors and their resolutions are high knowledge_value (0.7-1.0)
- Code being written or explained = high value
- Idle navigation, loading screens = low value (0.0-0.2)
- Each event should cover a distinct action or topic shift
- Use the transcript to understand INTENT, use OCR for CONTEXT of what was on screen
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    top_p=0.8,
                    top_k=40,
                    max_output_tokens=1200,
                    response_mime_type="application/json",
                    response_schema=_window_analysis_schema(start_sec, end_sec),
                ),
            )

            # Extract JSON from response, handling cases where Gemini adds extra text
            response_text = response.text.strip()
            # Find the first { and last } to extract only the JSON object
            start_idx = response_text.find('{')
            end_idx = response_text.rfind('}')
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = response_text[start_idx:end_idx + 1]
            else:
                json_str = response_text
            
            parsed = json.loads(json_str)
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
            logger.exception(f"Gemini window analysis failed: {e}")
            return LLMResult(success=False, error_message=str(e))

    # Keep backward-compatible method name
    async def process_screen_segments(
        self,
        raw_text: str,
        start_ms: int,
        end_ms: int,
        asset_context: str = "",
        transcript_text: str = "",
    ) -> LLMResult:
        """Backward-compatible wrapper around process_window."""
        return await self.process_window(
            start_sec=start_ms / 1000.0,
            end_sec=end_ms / 1000.0,
            ocr_text=raw_text,
            transcript_text=transcript_text,
            asset_context=asset_context,
        )

    async def extract_knowledge(
        self,
        text: str,
        context: str = "",
        start_sec: float = 0.0,
        end_sec: float = 0.0,
        transcript_text: str = "",
    ) -> LLMResult:
        """
        Extract structured knowledge units from OCR + transcript text.
        All extracted units now include start_sec / end_sec time anchors.
        """
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        has_ocr = bool(text and text.strip())
        has_transcript = bool(transcript_text and transcript_text.strip())

        ocr_block = _format_ocr_block(text)
        transcript_block = _format_transcript_block(transcript_text)

        prompt = f"""Extract structured knowledge from this recording segment \
(time: {start_sec:.1f}s - {end_sec:.1f}s{', ' + context if context else ''}).
{ocr_block}{transcript_block}

Extract:
- facts: general learnings, techniques, concepts explained
- errors: error messages shown or mentioned, with resolutions
- code_patterns: code snippets shown or dictated
- commands: CLI/shell commands used
- explanations: teaching moments where a concept is clearly explained

For each item, estimate start_sec and end_sec within [{start_sec:.1f}, {end_sec:.1f}].
Use the transcript to find WHERE in time an explanation happened.
Use OCR to find WHERE in time errors/code appeared on screen.
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=1200,
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
        has_video: bool = True,
        has_audio: bool = False,
    ) -> LLMResult:
        """
        Synthesize session-level summary with full knowledge_timeline.

        processed_segments now contains both ocr-based and transcript-based
        window summaries, each with their timeline_events.
        """
        if not self.api_key:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        duration_sec = duration_ms / 1000.0

        if has_video and has_audio:
            asset_type_desc = "screen recording with audio narration"
        elif has_audio:
            asset_type_desc = "audio recording"
        else:
            asset_type_desc = "screen recording"

        # Build a compact window-level summary for the prompt
        window_lines = []
        for seg in processed_segments[:30]:
            start = seg.get("start_sec", seg.get("start_ms", 0) / 1000)
            end = seg.get("end_sec", seg.get("end_ms", 0) / 1000)
            summary = seg.get("summary", "N/A")
            screen_type = seg.get("screen_type", "")
            kv = seg.get("knowledge_value", 0)
            intent = seg.get("user_intent", "")
            has_t = "🎙" if seg.get("has_transcript") else ""
            has_o = "🖥" if seg.get("has_ocr") else ""
            window_lines.append(
                f"[{start:.0f}s-{end:.0f}s]{has_t}{has_o} "
                f"kv={kv:.1f} screen={screen_type} | {summary}"
                + (f" | intent: {intent}" if intent else "")
            )

        windows_block = "\n".join(window_lines)

        # Include notable timeline events from high-value windows
        notable_events = []
        for seg in processed_segments:
            for evt in seg.get("timeline_events", []):
                if float(evt.get("knowledge_value", 0)) >= 0.6:
                    notable_events.append(
                        f"  [{evt.get('start_sec', 0):.0f}s] "
                        f"[{evt.get('event_type', '')}] {evt.get('activity_summary', '')}"
                    )
        events_block = "\n".join(notable_events[:40]) if notable_events else "  (none)"

        prompt = f"""Synthesize a knowledge summary for this {asset_type_desc} \
(title: {asset_title}, duration: {duration_sec:.0f}s).

WINDOW SUMMARIES ({len(processed_segments)} windows):
{windows_block}

NOTABLE EVENTS (high knowledge_value moments):
{events_block}

Produce:
1. session_title, primary_technology, difficulty_level, overall_summary
2. workflow steps (ordered by time, each with start_sec/end_sec)
3. problems_encountered and solutions_found (each with start_sec/end_sec)
4. knowledge_gained: list of key takeaways
5. knowledge_timeline: the complete ordered list of ALL notable moments across the session
   - Include every event_type (activity, error, solution, decision, explanation)
   - Each entry needs start_sec, end_sec, activity_summary, event_type, knowledge_value
   - Include spoken_content and screen_content where available
   - Order by start_sec ascending
   - Include at minimum all events with knowledge_value >= 0.5
"""

        try:
            model = genai.GenerativeModel(self.SYNTHESIS_MODEL)
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.5,
                    max_output_tokens=2000,
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