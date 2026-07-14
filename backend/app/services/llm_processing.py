"""
LLM Processing Service — OpenAI-compatible API Integration

Supports combined OCR + transcript input and produces timeline-based
knowledge output where every insight is anchored to a specific time range.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import get_logger
from app.ai.loaders.prompt_loader import load, render

logger = get_logger(__name__)

_openai_client: AsyncOpenAI | None = None

PARSE_RETRY_ATTEMPTS = 2
STRUCTURED_MODEL = settings.OPENAI_DEFAULT_MODEL


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY,
            base_url=settings.OPENAI_BASE_URL,
        )
    return _openai_client


# ─────────────────────────────────────────────────────────────────────────────
# Result container
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LLMResult:
    success: bool
    tokens_used: int = 0
    cost_usd: float = 0.0
    error_message: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None
    model_used: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builders (unchanged)
# ─────────────────────────────────────────────────────────────────────────────

def _format_transcript_block(transcript_text: str) -> str:
    if not transcript_text or not transcript_text.strip():
        return ""
    return f"\n\n─── SPEECH TRANSCRIPT ───\n{transcript_text.strip()}\n─────────────────────────"


def _format_ocr_block(ocr_text: str) -> str:
    if not ocr_text or not ocr_text.strip():
        return ""
    return f"\n\n─── SCREEN CONTENT (OCR) ───\n{ocr_text.strip()}\n────────────────────────────"


def _window_prompt_video_and_audio(
    start_sec: float,
    end_sec: float,
    ocr_text: str,
    transcript_text: str,
    asset_context: str,
) -> str:
    return render("assets/video_analysis.md",
        start_sec=start_sec,
        end_sec=end_sec,
        asset_context=asset_context or "N/A",
        ocr_block=_format_ocr_block(ocr_text),
        transcript_block=_format_transcript_block(transcript_text),
    )


def _window_prompt_audio_only(
    start_sec: float,
    end_sec: float,
    transcript_text: str,
    asset_context: str,
) -> str:
    return render("assets/audio_analysis.md",
        start_sec=start_sec,
        end_sec=end_sec,
        asset_context=asset_context or "N/A",
        transcript_block=_format_transcript_block(transcript_text),
    )


def _window_prompt_ocr_only(
    start_sec: float,
    end_sec: float,
    ocr_text: str,
    asset_context: str,
) -> str:
    return render("assets/ocr_analysis.md",
        start_sec=start_sec,
        end_sec=end_sec,
        asset_context=asset_context or "N/A",
        ocr_block=_format_ocr_block(ocr_text),
    )


def _knowledge_extraction_prompt(
    ocr_text: str,
    transcript_text: str,
    context: str,
    start_sec: float,
    end_sec: float,
) -> str:
    has_ocr = bool(ocr_text and ocr_text.strip())
    has_transcript = bool(transcript_text and transcript_text.strip())

    sources = []
    if has_ocr:
        sources.append("screen content (OCR)")
    if has_transcript:
        sources.append("speech transcript")

    source_desc = " + ".join(sources) if sources else "combined recording"

    return render("memory/knowledge_extraction.md",
        start_sec=start_sec,
        end_sec=end_sec,
        context=context or "N/A",
        source_desc=source_desc,
        ocr_block=_format_ocr_block(ocr_text),
        transcript_block=_format_transcript_block(transcript_text),
    )


def _session_synthesis_prompt(
    processed_segments: list[dict],
    asset_title: str,
    duration_sec: float,
    has_video: bool,
    has_audio: bool,
) -> str:
    if has_video and has_audio:
        asset_type_desc = "screen recording with audio narration"
    elif has_audio:
        asset_type_desc = "audio recording (lecture/meeting/tutorial)"
    else:
        asset_type_desc = "silent screen recording"

    window_lines = []
    for seg in processed_segments[:50]:
        start = seg.get("start_sec", seg.get("start_ms", 0) / 1000)
        end = seg.get("end_sec", seg.get("end_ms", 0) / 1000)
        summary = seg.get("summary", "N/A")
        screen_type = seg.get("screen_type", "")
        kv = seg.get("knowledge_value", 0)
        intent = seg.get("user_intent", "")
        has_t = "🎙" if seg.get("has_transcript") else ""
        has_o = "🖥" if seg.get("has_ocr") else ""
        line = (
            f"  [{start:.0f}s–{end:.0f}s]{has_t}{has_o} "
            f"kv={kv:.1f} screen={screen_type} | {summary}"
        )
        if intent:
            line += f"\n    intent: {intent}"
        window_lines.append(line)

    windows_block = "\n".join(window_lines)

    notable_events: list[str] = []
    all_events: list[dict] = []
    for seg in processed_segments:
        for evt in seg.get("timeline_events", []):
            all_events.append(evt)
            kv = float(evt.get("knowledge_value", 0))
            if kv >= 0.4:
                spoken = evt.get("spoken_content", "")
                spoken_excerpt = f' | "{spoken[:80]}…"' if spoken else ""
                notable_events.append(
                    f"  [{evt.get('start_sec', 0):.0f}s–{evt.get('end_sec', 0):.0f}s] "
                    f"[{evt.get('event_type', '')}] kv={kv:.1f} "
                    f"{evt.get('activity_summary', '')}{spoken_excerpt}"
                )

    events_block = "\n".join(notable_events[:60]) if notable_events else "  (none recorded)"
    total_events = len(all_events)

    return render("synthesis/session_summary.md",
        asset_type_desc=asset_type_desc,
        asset_title=asset_title,
        duration_sec=duration_sec,
        window_count=len(processed_segments),
        total_events=total_events,
        windows_block=windows_block,
        events_block=events_block,
    )


# ─────────────────────────────────────────────────────────────────────────────
# JSON schema definitions (as prompt instructions — model must match)
# ─────────────────────────────────────────────────────────────────────────────

# The expected output shapes are documented inline in the prompts above.
# We use response_format="json_object" to guarantee valid JSON, and the
# detailed prompt instructions guide the model to produce the correct structure.
# No additional schema enforcement is needed beyond the prompt.


# ─────────────────────────────────────────────────────────────────────────────
# Service class
# ─────────────────────────────────────────────────────────────────────────────

class StructuredResponseParseError(ValueError):
    """Model returned 200 OK but response is not valid structured JSON."""


class LLMProcessingService:
    """LLM processing via OpenAI-compatible API with structured JSON output."""

    def __init__(self) -> None:
        self._model = STRUCTURED_MODEL

    async def _generate_structured(
        self,
        prompt: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        log_label: str = "LLM",
    ) -> LLMResult:
        """Generate structured JSON response using OpenAI-compatible chat completion."""
        client = _get_client()

        last_error: Optional[str] = None

        for attempt in range(PARSE_RETRY_ATTEMPTS + 1):
            try:
                response = await client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": load("system/llm_system.md")},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )

                content = response.choices[0].message.content or ""

                if not content.strip():
                    raise StructuredResponseParseError("Empty model response")

                # Extract JSON block
                start_idx = content.find("{")
                end_idx = content.rfind("}")
                if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                    content = content[start_idx : end_idx + 1]

                parsed = json.loads(content)

                usage = response.usage
                if usage:
                    total_tokens = usage.total_tokens or 0
                    prompt_tokens = usage.prompt_tokens or 0
                    output_tokens = usage.completion_tokens or 0
                    cost = (prompt_tokens * 0.075 + output_tokens * 0.30) / 1_000_000
                else:
                    total_tokens = 0
                    cost = 0.0

                return LLMResult(
                    success=True,
                    parsed_data=parsed,
                    tokens_used=total_tokens,
                    cost_usd=cost,
                    model_used=self._model,
                )

            except StructuredResponseParseError as e:
                last_error = str(e)
                if attempt < PARSE_RETRY_ATTEMPTS:
                    logger.warning(
                        f"{log_label}: parse failed "
                        f"(attempt {attempt + 1}/{PARSE_RETRY_ATTEMPTS + 1}), retrying — {e}"
                    )
                    continue
                logger.error(f"{log_label}: parse failed after retries — {e}")

            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower() or "rate_limit" in str(e).lower():
                    logger.warning(f"{log_label}: quota error, retrying — {e}")
                    continue
                logger.exception(f"{log_label}: request failed — {e}")
                return LLMResult(success=False, error_message=str(e))

        return LLMResult(success=False, error_message=last_error or "All attempts failed")

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

        Selects the appropriate prompt based on what data is available:
          • Both OCR + transcript  → richest prompt
          • Transcript only        → audio-only prompt (lecture/meeting focused)
          • OCR only               → silent screen recording prompt
          • Neither                → returns empty result immediately
        """
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
                    "summary": "No content available for this window.",
                    "topics": [],
                    "entities": [],
                    "searchable_keywords": [],
                    "timeline_events": [],
                },
            )

        if has_ocr and has_transcript:
            prompt = _window_prompt_video_and_audio(
                start_sec, end_sec, ocr_text, transcript_text, asset_context
            )
        elif has_transcript:
            prompt = _window_prompt_audio_only(
                start_sec, end_sec, transcript_text, asset_context
            )
        else:
            prompt = _window_prompt_ocr_only(
                start_sec, end_sec, ocr_text, asset_context
            )

        return await self._generate_structured(
            prompt=prompt,
            temperature=0.2,
            max_tokens=2000,
            log_label="Window analysis",
        )

    async def process_screen_segments(
        self,
        raw_text: str,
        start_ms: int,
        end_ms: int,
        asset_context: str = "",
        transcript_text: str = "",
    ) -> LLMResult:
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
        """
        prompt = _knowledge_extraction_prompt(
            ocr_text=text,
            transcript_text=transcript_text,
            context=context,
            start_sec=start_sec,
            end_sec=end_sec,
        )

        return await self._generate_structured(
            prompt=prompt,
            temperature=0.2,
            max_tokens=2000,
            log_label="Knowledge extraction",
        )

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
        """
        duration_sec = duration_ms / 1000.0

        prompt = _session_synthesis_prompt(
            processed_segments=processed_segments,
            asset_title=asset_title,
            duration_sec=duration_sec,
            has_video=has_video,
            has_audio=has_audio,
        )

        return await self._generate_structured(
            prompt=prompt,
            temperature=0.2,
            max_tokens=8192,
            log_label="Session synthesis",
        )


llm_service = LLMProcessingService()
