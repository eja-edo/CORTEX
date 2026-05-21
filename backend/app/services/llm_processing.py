"""
LLM Processing Service — Gemini API Integration

Supports combined OCR + transcript input and produces timeline-based
knowledge output where every insight is anchored to a specific time range.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional

from google.genai import types

from app.config import settings
from app.services.agent.model_client import (
    AllModelsExhaustedError,
    ModelClient,
    STRUCTURED_JSON_MODELS,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Gemma models return HTTP 200 with truncated/invalid JSON for response_schema calls.
_model_client = ModelClient(models=STRUCTURED_JSON_MODELS)

PARSE_RETRY_ATTEMPTS = 2


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
# Schema helpers (unchanged from original — keep them compact)
# ─────────────────────────────────────────────────────────────────────────────

def _entity_schema() -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "type": types.Schema(
                type=types.Type.STRING,
                enum=["url", "code", "error", "person", "tool", "file"],
            ),
            "value": types.Schema(type=types.Type.STRING),
            "confidence": types.Schema(type=types.Type.NUMBER),
        },
        required=["type", "value", "confidence"],
    )


def _timeline_event_schema(start_sec: float, end_sec: float) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "start_sec": types.Schema(
                type=types.Type.NUMBER,
                description=f"Start time in seconds (>= {start_sec:.1f})",
            ),
            "end_sec": types.Schema(
                type=types.Type.NUMBER,
                description=f"End time in seconds (<= {end_sec:.1f})",
            ),
            "activity_summary": types.Schema(
                type=types.Type.STRING,
                description="2-3 sentences describing exactly what happened at this moment",
            ),
            "spoken_content": types.Schema(
                type=types.Type.STRING,
                description="Verbatim or near-verbatim transcript excerpt for this moment",
            ),
            "screen_content": types.Schema(
                type=types.Type.STRING,
                description="Key text or UI elements visible on screen at this moment",
            ),
            "screen_type": types.Schema(
                type=types.Type.STRING,
                enum=["browser", "editor", "terminal", "settings", "document", "other"],
            ),
            "application": types.Schema(type=types.Type.STRING),
            "event_type": types.Schema(
                type=types.Type.STRING,
                enum=["activity", "error", "solution", "decision", "explanation"],
            ),
            "knowledge_value": types.Schema(
                type=types.Type.NUMBER,
                description="0.0 = trivial/idle, 1.0 = critical learning moment",
            ),
            "topics": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            "entities": types.Schema(
                type=types.Type.ARRAY,
                items=_entity_schema(),
            ),
            "keywords": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
        },
        required=[
            "start_sec", "end_sec", "activity_summary",
            "event_type", "knowledge_value", "topics", "keywords",
        ],
    )


def _window_analysis_schema(start_sec: float, end_sec: float) -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "screen_type": types.Schema(
                type=types.Type.STRING,
                enum=["browser", "editor", "terminal", "settings", "document", "other"],
            ),
            "application": types.Schema(type=types.Type.STRING),
            "user_intent": types.Schema(
                type=types.Type.STRING,
                description="Detailed description of the user's goal in this window",
            ),
            "knowledge_value": types.Schema(
                type=types.Type.NUMBER,
                description="Overall knowledge value 0.0-1.0 for this window",
            ),
            "summary": types.Schema(
                type=types.Type.STRING,
                description=(
                    "4-6 sentence summary covering: what was on screen, "
                    "what the user was trying to do, what they actually did, "
                    "and any problems or insights that occurred."
                ),
            ),
            "topics": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            "entities": types.Schema(
                type=types.Type.ARRAY,
                items=_entity_schema(),
            ),
            "searchable_keywords": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            "timeline_events": types.Schema(
                type=types.Type.ARRAY,
                description=(
                    "Fine-grained events within this window, ordered by start_sec. "
                    "Each event covers a distinct action, topic shift, or moment of interest. "
                    "Be thorough — include all meaningful events, not just high-value ones."
                ),
                items=_timeline_event_schema(start_sec, end_sec),
            ),
        },
        required=[
            "knowledge_value", "summary", "topics", "searchable_keywords",
            "timeline_events",
        ],
    )


def _knowledge_extraction_schema() -> types.Schema:
    confidence_field = types.Schema(type=types.Type.NUMBER)
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "facts": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "content": types.Schema(type=types.Type.STRING),
                        "confidence": confidence_field,
                        "context": types.Schema(type=types.Type.STRING),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["content", "confidence", "start_sec", "end_sec"],
                ),
            ),
            "errors": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "message": types.Schema(type=types.Type.STRING),
                        "error_type": types.Schema(
                            type=types.Type.STRING,
                            enum=["connection", "syntax", "runtime", "logic", "other"],
                        ),
                        "resolution": types.Schema(type=types.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["message", "resolution", "confidence", "start_sec", "end_sec"],
                ),
            ),
            "code_patterns": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "snippet": types.Schema(type=types.Type.STRING),
                        "language": types.Schema(
                            type=types.Type.STRING,
                            enum=["python", "javascript", "typescript", "bash", "sql", "other"],
                        ),
                        "purpose": types.Schema(type=types.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["snippet", "language", "purpose", "confidence", "start_sec", "end_sec"],
                ),
            ),
            "commands": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "command": types.Schema(type=types.Type.STRING),
                        "platform": types.Schema(
                            type=types.Type.STRING,
                            enum=["docker", "bash", "powershell", "npm", "pip", "git", "other"],
                        ),
                        "purpose": types.Schema(type=types.Type.STRING),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["command", "platform", "purpose", "start_sec", "end_sec"],
                ),
            ),
            "explanations": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "topic": types.Schema(type=types.Type.STRING),
                        "explanation": types.Schema(type=types.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["topic", "explanation", "confidence", "start_sec", "end_sec"],
                ),
            ),
            "decisions": types.Schema(
                type=types.Type.ARRAY,
                description="Key decisions made by the user with their reasoning",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "decision": types.Schema(type=types.Type.STRING),
                        "rationale": types.Schema(type=types.Type.STRING),
                        "alternatives_considered": types.Schema(type=types.Type.STRING),
                        "confidence": confidence_field,
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["decision", "rationale", "confidence", "start_sec", "end_sec"],
                ),
            ),
        },
    )


def _session_synthesis_schema() -> types.Schema:
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "session_title": types.Schema(type=types.Type.STRING),
            "primary_technology": types.Schema(type=types.Type.STRING),
            "secondary_technologies": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            "difficulty_level": types.Schema(
                type=types.Type.STRING,
                enum=["beginner", "intermediate", "advanced"],
            ),
            "overall_summary": types.Schema(
                type=types.Type.STRING,
                description=(
                    "5-8 sentence executive summary covering: what was the goal, "
                    "what approach was taken, what worked, what didn't, and what "
                    "the end state was."
                ),
            ),
            "tags": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(type=types.Type.STRING),
            ),
            "workflow": types.Schema(
                type=types.Type.ARRAY,
                description="Ordered list of high-level steps taken in this session",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "step": types.Schema(type=types.Type.INTEGER),
                        "description": types.Schema(type=types.Type.STRING),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["step", "description", "start_sec", "end_sec"],
                ),
            ),
            "problems_encountered": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "problem": types.Schema(type=types.Type.STRING),
                        "context": types.Schema(type=types.Type.STRING),
                        "resolution": types.Schema(type=types.Type.STRING),
                        "time_to_resolve_sec": types.Schema(type=types.Type.NUMBER),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["problem", "start_sec", "end_sec"],
                ),
            ),
            "solutions_found": types.Schema(
                type=types.Type.ARRAY,
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "problem": types.Schema(type=types.Type.STRING),
                        "solution": types.Schema(type=types.Type.STRING),
                        "generalizability": types.Schema(type=types.Type.NUMBER),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["problem", "solution", "start_sec", "end_sec"],
                ),
            ),
            "knowledge_gained": types.Schema(
                type=types.Type.ARRAY,
                description=(
                    "Exhaustive list of distinct things learned or demonstrated in "
                    "this session — every concept, technique, and insight, stated as "
                    "a complete sentence."
                ),
                items=types.Schema(type=types.Type.STRING),
            ),
            "key_quotes": types.Schema(
                type=types.Type.ARRAY,
                description="Most important verbatim or near-verbatim spoken statements",
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "quote": types.Schema(type=types.Type.STRING),
                        "context": types.Schema(type=types.Type.STRING),
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                    },
                    required=["quote", "start_sec"],
                ),
            ),
            "knowledge_timeline": types.Schema(
                type=types.Type.ARRAY,
                description=(
                    "Complete ordered timeline of ALL notable moments across the "
                    "session. Include every event_type. Order by start_sec. "
                    "Be exhaustive — the user should be able to understand the "
                    "full session from this timeline alone."
                ),
                items=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        "start_sec": types.Schema(type=types.Type.NUMBER),
                        "end_sec": types.Schema(type=types.Type.NUMBER),
                        "activity_summary": types.Schema(type=types.Type.STRING),
                        "spoken_content": types.Schema(type=types.Type.STRING),
                        "screen_content": types.Schema(type=types.Type.STRING),
                        "screen_type": types.Schema(
                            type=types.Type.STRING,
                            enum=["browser", "editor", "terminal", "settings", "document", "other"],
                        ),
                        "application": types.Schema(type=types.Type.STRING),
                        "event_type": types.Schema(
                            type=types.Type.STRING,
                            enum=["activity", "error", "solution", "decision", "explanation"],
                        ),
                        "knowledge_value": types.Schema(type=types.Type.NUMBER),
                        "topics": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                        ),
                        "keywords": types.Schema(
                            type=types.Type.ARRAY,
                            items=types.Schema(type=types.Type.STRING),
                        ),
                    },
                    required=[
                        "start_sec", "end_sec", "activity_summary",
                        "event_type", "knowledge_value",
                    ],
                ),
            ),
        },
        required=[
            "session_title", "difficulty_level", "overall_summary",
            "tags", "knowledge_timeline", "knowledge_gained",
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Prompt builders
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
    return f"""You are an expert analyst processing a screen recording with audio narration.
Segment: {start_sec:.1f}s – {end_sec:.1f}s  |  Asset: {asset_context}
{_format_ocr_block(ocr_text)}{_format_transcript_block(transcript_text)}

═══ YOUR TASK ═══

Produce a DETAILED analysis of this segment. Your output will be the primary source of
information about this moment in the recording, so be thorough and specific.

1. SUMMARY (4-6 sentences)
   • What application/website was open?
   • What was the user actively trying to accomplish?
   • What actions did they take (clicks, typing, navigation, commands)?
   • What was the outcome — success, error, partial progress?
   • Any important insight, decision, or teaching moment?

2. USER INTENT
   Describe the user's goal in this window in a complete sentence.

3. TIMELINE EVENTS (be exhaustive — split into distinct moments)
   For EACH meaningful action or topic shift create a separate event with:
   • start_sec / end_sec  (pin to actual timing within {start_sec:.1f}–{end_sec:.1f}s)
   • activity_summary: 2-3 sentences — what specifically happened
   • spoken_content: copy the relevant transcript excerpt verbatim
   • screen_content: copy the most important text/code visible on screen
   • event_type: activity | error | solution | decision | explanation
   • knowledge_value scoring guide:
       1.0  — Critical: error found+fixed, key concept explained, architecture decision
       0.8  — Important: new feature implemented, bug identified, tool/API demonstrated
       0.6  — Useful: configuration change, code refactor, workflow step
       0.4  — Moderate: navigation, searching, reading docs
       0.2  — Low: minor UI interaction, waiting, loading
       0.0  — Trivial: idle, lock screen, blank content
   • topics: specific technology names, concept names (e.g. "React hooks", "SQL JOIN")
   • keywords: searchable terms a user would type to find this moment

4. ENTITIES — extract ALL occurrences of:
   • URLs visited
   • Code identifiers (function names, class names, variable names)
   • Error messages (exact text)
   • Tools and libraries used
   • File paths

Use OCR to understand WHAT was on screen; use transcript to understand WHY and the user's intent.
"""


def _window_prompt_audio_only(
    start_sec: float,
    end_sec: float,
    transcript_text: str,
    asset_context: str,
) -> str:
    return f"""You are an expert analyst processing an audio recording (no screen content).
Segment: {start_sec:.1f}s – {end_sec:.1f}s  |  Asset: {asset_context}
{_format_transcript_block(transcript_text)}

═══ YOUR TASK ═══

Produce a DETAILED analysis of this spoken segment. The transcript is your only source,
so extract maximum value from it.

1. SUMMARY (4-6 sentences)
   • What topic or subject is being discussed?
   • Who is speaking (if identifiable — e.g. different speakers, instructor, student)?
   • What is the core message or argument being made?
   • What specific information, instructions, or explanations were given?
   • What conclusions or decisions were reached?

2. USER INTENT
   What is the speaker trying to communicate or accomplish in this segment?

3. TIMELINE EVENTS (split into distinct topic shifts or key statements)
   For EACH distinct topic or important statement create a separate event:
   • start_sec / end_sec  (pin to timing within {start_sec:.1f}–{end_sec:.1f}s)
   • activity_summary: 2-3 sentences capturing the substance of what was said
   • spoken_content: the most important verbatim excerpt (20-60 words)
   • screen_content: leave empty (no screen)
   • event_type:
       explanation — concept or process being explained
       decision    — a choice or recommendation being made
       activity    — describing an action or procedure
       error       — describing a problem or mistake
       solution    — describing how to fix something
   • knowledge_value:
       1.0  — Core concept explained, critical instruction given
       0.8  — Important technique, methodology, or insight shared
       0.6  — Useful detail, example, or context provided
       0.4  — Background information, transition between topics
       0.2  — Filler, repetition, social pleasantries
   • topics: specific subject areas discussed
   • keywords: terms a learner would search for to find this moment

4. ENTITIES — extract ALL:
   • Named technologies, tools, libraries, frameworks
   • Named people, organizations, products
   • URLs or file paths mentioned verbally
   • Specific commands or code mentioned in speech

Be comprehensive. This transcript may be from a lecture, tutorial, meeting, or
narrated demonstration — treat it accordingly.
"""


def _window_prompt_ocr_only(
    start_sec: float,
    end_sec: float,
    ocr_text: str,
    asset_context: str,
) -> str:
    return f"""You are an expert analyst processing a silent screen recording (no audio).
Segment: {start_sec:.1f}s – {end_sec:.1f}s  |  Asset: {asset_context}
{_format_ocr_block(ocr_text)}

═══ YOUR TASK ═══

Produce a DETAILED analysis based solely on what was visible on screen.

1. SUMMARY (4-6 sentences)
   • What application or website was open?
   • What content or data was displayed?
   • What was the user apparently trying to do (inferred from screen state)?
   • What changes occurred between frames (new content, errors, navigation)?
   • Any error messages, code, commands, or important text visible?

2. USER INTENT
   Infer the user's goal from the screen content alone.

3. TIMELINE EVENTS (split by meaningful screen changes)
   • start_sec / end_sec within {start_sec:.1f}–{end_sec:.1f}s
   • activity_summary: describe what is shown and what it implies about the user's action
   • spoken_content: leave empty (no audio)
   • screen_content: exact copy of the most important visible text
   • event_type: activity | error | solution | decision | explanation
   • knowledge_value (same scale as above)
   • topics & keywords: derived from visible content

4. ENTITIES — extract ALL visible:
   • URLs in address bars or on screen
   • Error messages (exact text)
   • Code identifiers and snippets
   • File paths, commands visible in terminal
   • Tool/library names visible on screen

Infer as much context as possible from what is shown, but do not fabricate
information that is not present in the OCR text.
"""


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

    return f"""You are extracting structured knowledge units from a recording segment.
Time range: {start_sec:.1f}s – {end_sec:.1f}s
Context: {context or "N/A"}
Sources available: {source_desc}
{_format_ocr_block(ocr_text)}{_format_transcript_block(transcript_text)}

═══ EXTRACTION INSTRUCTIONS ═══

Extract EVERY piece of reusable knowledge. Be exhaustive — it is better to
include a borderline item than to miss something useful.

FACTS
  • General learnings, techniques, best practices, concepts demonstrated
  • Configuration details, parameter values, settings that matter
  • "I learned that X works like Y" style insights
  • Each fact should be a self-contained, reusable statement
  • Minimum useful length: one clear sentence

ERRORS
  • Every error message shown on screen or mentioned verbally
  • Include the EXACT error text as `message`
  • For `resolution`: what was done to fix it (or "unresolved" if not fixed)
  • Include partial errors — even if not fully resolved, document them

CODE PATTERNS
  • Any code snippet visible on screen or dictated verbally
  • Include enough context to understand the pattern (not just one line)
  • `purpose`: what this code accomplishes

COMMANDS
  • Every CLI/shell/terminal command visible or spoken
  • Include flags and arguments
  • `purpose`: what the command does

EXPLANATIONS
  • Any moment where a concept is explained, defined, or demonstrated
  • Both verbal explanations (from transcript) and implicit demonstrations (from screen)
  • `explanation`: a complete, standalone explanation of the topic

DECISIONS
  • Choices the user made with explicit or implicit reasoning
  • Technology choices, architectural decisions, workaround selections
  • `rationale`: why this choice was made (even if inferred)
  • `alternatives_considered`: other options mentioned or implied

For each item, estimate start_sec/end_sec within [{start_sec:.1f}, {end_sec:.1f}]:
  • Use transcript timing for verbal explanations and decisions
  • Use frame timestamps for screen-based errors and code
  • When uncertain, use the window boundaries

Do NOT skip items because they seem minor — the user may search for them later.
"""


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

    # Collect ALL notable events (kv >= 0.4) from window timeline_events
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

    return f"""You are synthesizing a complete knowledge report for a {asset_type_desc}.

Title: {asset_title}
Duration: {duration_sec:.0f}s ({duration_sec/60:.1f} minutes)
Windows analyzed: {len(processed_segments)}
Total timeline events: {total_events}

─── WINDOW-BY-WINDOW SUMMARY ───
{windows_block}

─── NOTABLE EVENTS (kv ≥ 0.4) ───
{events_block}

═══ SYNTHESIS INSTRUCTIONS ═══

Your output is the PERMANENT knowledge record of this session. It must be:
  • Complete — someone who has never seen the recording should understand what happened
  • Accurate — only include things that actually occurred
  • Useful — written so the user can search, review, and learn from it later

1. SESSION TITLE
   A specific, descriptive title (not generic) — e.g. "Debugging Docker Compose
   networking issue in FastAPI app" not "Coding session".

2. OVERALL SUMMARY (5-8 sentences)
   Cover: What was the goal? What approach was used? What went well?
   What problems occurred and how were they resolved? What was the end state?
   What are the key takeaways?

3. PRIMARY + SECONDARY TECHNOLOGIES
   List every technology, framework, library, tool, platform that appeared.

4. DIFFICULTY LEVEL
   beginner / intermediate / advanced based on the content's technical depth.

5. WORKFLOW (ordered steps)
   Break the session into its logical phases/steps, each with start_sec/end_sec.
   Be specific — "Installed dependencies and configured environment (0s–180s)"
   not "Set up project".

6. PROBLEMS ENCOUNTERED
   Every problem, error, blocker, or confusion — include:
   • Exact error message if available
   • Context (what they were trying to do)
   • Resolution (what fixed it, or "unresolved")
   • Approximate time to resolve

7. SOLUTIONS FOUND
   Every successful fix, workaround, or discovery — include the specific solution
   and how reusable/generalizable it is (0.0=very specific, 1.0=universally applicable).

8. KNOWLEDGE GAINED
   An EXHAUSTIVE list of distinct learnings — every concept, technique, and insight.
   Write each as a complete sentence starting with an action verb:
   "Learned that...", "Discovered that...", "Demonstrated how to...", etc.
   Aim for at least one item per 2-3 minutes of content.

9. KEY QUOTES
   The 3-8 most important things said (verbatim or near-verbatim).
   These should be the statements that best capture the session's insights.

10. KNOWLEDGE TIMELINE (MOST IMPORTANT)
    The complete, ordered timeline of ALL notable moments.
    Include EVERY event with knowledge_value >= 0.3.
    For audio sessions: include every distinct topic, explanation, and decision.
    For video sessions: include every meaningful screen state change + speech.
    Each entry must have:
    • start_sec, end_sec (precise timing)
    • activity_summary: 2-3 sentences fully describing the moment
    • spoken_content: key verbatim excerpt (if audio available)
    • screen_content: key visible text (if video available)
    • event_type: activity | error | solution | decision | explanation
    • knowledge_value: 0.0–1.0
    • topics: specific subjects
    • keywords: searchable terms

    The timeline should be dense enough that the user can reconstruct the
    entire session from it — aim for one entry per 30-60 seconds of content.
"""


# ─────────────────────────────────────────────────────────────────────────────
# Service class
# ─────────────────────────────────────────────────────────────────────────────

class StructuredResponseParseError(ValueError):
    """Model returned 200 OK but response is not valid structured JSON."""


def _response_finish_reason(response: types.GenerateContentResponse) -> Optional[str]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    reason = getattr(candidates[0], "finish_reason", None)
    return str(reason) if reason is not None else None


def _parse_json_response(response: types.GenerateContentResponse) -> dict[str, Any]:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, dict):
        return parsed

    if parsed is not None and hasattr(parsed, "model_dump"):
        return parsed.model_dump()

    response_text = (getattr(response, "text", "") or "").strip()
    if not response_text:
        finish_reason = _response_finish_reason(response)
        raise StructuredResponseParseError(
            f"Empty model response (finish_reason={finish_reason})"
        )

    start_idx = response_text.find("{")
    end_idx = response_text.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        response_text = response_text[start_idx : end_idx + 1]

    try:
        return json.loads(response_text)
    except json.JSONDecodeError as exc:
        finish_reason = _response_finish_reason(response)
        preview = response_text[:300].replace("\n", " ")
        raise StructuredResponseParseError(
            f"Invalid JSON (finish_reason={finish_reason}, len={len(response_text)}): {exc}. "
            f"Preview: {preview!r}"
        ) from exc


def _extract_usage_and_cost(response: types.GenerateContentResponse) -> tuple[int, float]:
    usage = getattr(response, "usage_metadata", None)
    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    total_tokens = getattr(usage, "total_token_count", 0) or (prompt_tokens + output_tokens)
    cost = (prompt_tokens * 0.075 + output_tokens * 0.30) / 1_000_000
    return total_tokens, cost


def _prompt_to_contents(prompt: str) -> list[types.Content]:
    return [
        types.Content(
            role="user",
            parts=[types.Part.from_text(text=prompt)],
        )
    ]


class GeminiProcessingService:
    """Gemini LLM processing via shared ModelClient (retry + model fallback)."""

    async def _generate_structured(
        self,
        prompt: str,
        config: types.GenerateContentConfig,
        estimated_tokens: int,
        log_label: str,
    ) -> LLMResult:
        if not settings.GEMINI_API_KEY:
            return LLMResult(success=False, error_message="GEMINI_API_KEY not configured")

        last_parse_error: Optional[str] = None

        for attempt in range(PARSE_RETRY_ATTEMPTS + 1):
            try:
                model_used, response = await _model_client.generate(
                    _prompt_to_contents(prompt),
                    config,
                    estimated_tokens=estimated_tokens,
                )
                parsed = _parse_json_response(response)
                total_tokens, cost = _extract_usage_and_cost(response)

                return LLMResult(
                    success=True,
                    parsed_data=parsed,
                    tokens_used=total_tokens,
                    cost_usd=cost,
                    model_used=model_used,
                )

            except StructuredResponseParseError as e:
                last_parse_error = str(e)
                if attempt < PARSE_RETRY_ATTEMPTS:
                    logger.warning(
                        f"{log_label}: structured JSON parse failed "
                        f"(attempt {attempt + 1}/{PARSE_RETRY_ATTEMPTS + 1}), retrying — {e}"
                    )
                    continue
                logger.error(f"{log_label}: structured JSON parse failed after retries — {e}")
                return LLMResult(success=False, error_message=last_parse_error)

            except AllModelsExhaustedError as e:
                logger.error(f"{log_label}: all models exhausted — {e}")
                return LLMResult(success=False, error_message=str(e))

            except Exception as e:
                logger.exception(f"{log_label} failed: {e}")
                return LLMResult(success=False, error_message=str(e))

        return LLMResult(
            success=False,
            error_message=last_parse_error or "Unknown structured output error",
        )

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

        # Select prompt based on available data
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
            config=types.GenerateContentConfig(
                temperature=0.2,
                top_p=0.85,
                top_k=40,
                max_output_tokens=2000,
                response_mime_type="application/json",
                response_schema=_window_analysis_schema(start_sec, end_sec),
            ),
            estimated_tokens=2000,
            log_label="Gemini window analysis",
        )

    # Keep backward-compatible method name
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
        Now includes decisions as a first-class extraction category.
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
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=2000,
                response_mime_type="application/json",
                response_schema=_knowledge_extraction_schema(),
            ),
            estimated_tokens=2000,
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
        Uses a dense, exhaustive prompt that pushes the model to capture
        everything rather than summarizing aggressively.
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
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=8192,
                response_mime_type="application/json",
                response_schema=_session_synthesis_schema(),
            ),
            estimated_tokens=8192,
            log_label="Session synthesis",
        )


gemini_service = GeminiProcessingService()
