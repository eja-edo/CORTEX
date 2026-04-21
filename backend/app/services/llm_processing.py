"""
LLM Processing Service — Gemini API Integration

Handles LLM-based analysis of OCR frames and knowledge extraction.
"""

import json
from dataclasses import dataclass
from typing import Any, Optional, Literal

import google.generativeai as genai
from pydantic import BaseModel, Field

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# Pydantic models for JSON schema generation
class Entity(BaseModel):
    """Entity detected in screen content."""
    type: Literal["url", "code", "error"]
    value: str
    confidence: float


class ScreenSegmentResponse(BaseModel):
    """Screen segment analysis response."""
    screen_type: Literal["browser", "editor", "terminal", "settings", "other"]
    application: Optional[str] = None
    user_intent: str
    knowledge_value: float = Field(..., ge=0.0, le=1.0)
    summary: str
    topics: list[str]
    entities: list[Entity] = Field(default_factory=list)
    searchable_keywords: list[str]


class Fact(BaseModel):
    """Fact extracted from text."""
    content: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    context: Optional[str] = None


class ErrorInfo(BaseModel):
    """Error information."""
    message: str
    error_type: Literal["connection", "syntax", "runtime"] = "runtime"
    resolution: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class CodePattern(BaseModel):
    """Code pattern found."""
    snippet: str
    language: Literal["python", "javascript", "bash", "sql"]
    purpose: str
    confidence: float = Field(..., ge=0.0, le=1.0)


class Command(BaseModel):
    """Command found."""
    command: str
    platform: Literal["docker", "bash", "powershell"]
    purpose: str


class KnowledgeExtractionResponse(BaseModel):
    """Knowledge extraction response."""
    facts: list[Fact] = Field(default_factory=list)
    errors: list[ErrorInfo] = Field(default_factory=list)
    code_patterns: list[CodePattern] = Field(default_factory=list)
    commands: list[Command] = Field(default_factory=list)


class WorkflowStep(BaseModel):
    """Workflow step."""
    step: int
    description: str
    duration_ms: Optional[int] = None


class ProblemEncountered(BaseModel):
    """Problem encountered."""
    problem: str
    context: Optional[str] = None
    resolution: Optional[str] = None


class SolutionFound(BaseModel):
    """Solution found."""
    problem: str
    solution: str
    generalizability: float = Field(default=0.5, ge=0.0, le=1.0)


class SessionSynthesisResponse(BaseModel):
    """Session synthesis response."""
    session_title: str
    primary_technology: Optional[str] = None
    difficulty_level: Literal["beginner", "intermediate", "advanced"]
    overall_summary: str
    tags: list[str]
    workflow: list[WorkflowStep] = Field(default_factory=list)
    problems_encountered: list[ProblemEncountered] = Field(default_factory=list)
    solutions_found: list[SolutionFound] = Field(default_factory=list)
    knowledge_gained: list[str] = Field(default_factory=list)


@dataclass
class LLMResult:
    """Result from LLM processing."""

    success: bool
    tokens_used: int = 0
    cost_usd: float = 0.0
    error_message: Optional[str] = None
    parsed_data: Optional[dict[str, Any]] = None


class GeminiProcessingService:
    """Service for Gemini API-based LLM processing."""

    def __init__(self) -> None:
        self.api_key = settings.GEMINI_API_KEY
        self.timeout = 60
        self.DEFAULT_MODEL = settings.GEMINI_DEFAULT_MODEL 
        self.SYNTHESIS_MODEL = settings.GEMINI_SYNTHESIS_MODEL 

        if self.api_key:
            genai.configure(api_key=self.api_key)

    def process_screen_segments(
        self,
        raw_text: str,
        start_ms: int,
        end_ms: int,
        asset_context: str = "",
    ) -> LLMResult:
        """
        Process OCR text from a screen window (30s) using Gemini.

        Returns:
            LLMResult with screen_type, user_intent, knowledge_value, summary, etc.
        """
        if not self.api_key:
            return LLMResult(
                success=False,
                error_message="GEMINI_API_KEY not configured",
            )

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
                tokens_used=0,
                cost_usd=0.0,
            )

        prompt = f"""
Analyze this OCR text from a screen recording (timestamp {start_ms}ms - {end_ms}ms, asset: {asset_context}).

OCR TEXT:
{raw_text}

Focus on:
- Detecting screen content type
- Understanding user workflows
- Identifying errors, code patterns, commands
- Knowledge value: 0 = screenshot, 1 = critical learning moment
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    top_p=0.8,
                    top_k=40,
                    max_output_tokens=500,
                    response_schema=ScreenSegmentResponse.model_json_schema(),
                    response_mime_type="application/json",
                ),
            )

            # Response is already in JSON format
            parsed = json.loads(response.text)

            # Estimate tokens (rough approximation)
            prompt_tokens = len(prompt) // 4
            response_tokens = len(response.text) // 4
            total_tokens = prompt_tokens + response_tokens

            # Cost estimation: gemini-1.5-flash $0.075/1M input, $0.30/1M output
            cost = (prompt_tokens * 0.075 + response_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Gemini screen analysis failed: {e}")
            return LLMResult(
                success=False,
                error_message=str(e),
            )

    def extract_knowledge(self, text: str, context: str = "") -> LLMResult:
        """
        Extract structured knowledge from OCR text.

        Returns:
            LLMResult with facts, errors, code_patterns, commands
        """
        if not self.api_key:
            return LLMResult(
                success=False,
                error_message="GEMINI_API_KEY not configured",
            )

        prompt = f"""
Extract structured knowledge from this OCR text{' (' + context + ')' if context else ''}.

TEXT:
{text}

Extract facts, errors, code patterns, and commands found in the text.
"""

        try:
            model = genai.GenerativeModel(self.DEFAULT_MODEL)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=1000,
                    response_schema=KnowledgeExtractionResponse.model_json_schema(),
                    response_mime_type="application/json",
                ),
            )

            # Response is already in JSON format
            parsed = json.loads(response.text)

            # Estimate tokens
            prompt_tokens = len(prompt) // 4
            response_tokens = len(response.text) // 4
            total_tokens = prompt_tokens + response_tokens
            cost = (prompt_tokens * 0.075 + response_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Knowledge extraction failed: {e}")
            return LLMResult(
                success=False,
                error_message=str(e),
            )

    def synthesize_session(
        self,
        processed_segments: list[dict],
        asset_title: str = "",
        duration_ms: int = 0,
    ) -> LLMResult:
        """
        Synthesize a session-level summary from multiple processed segments.

        Args:
            processed_segments: List of dicts with summary, screen_type, topics, etc.
            asset_title: Title for the session
            duration_ms: Total duration in milliseconds

        Returns:
            LLMResult with session_title, overall_summary, tags, workflow, etc.
        """
        if not self.api_key:
            return LLMResult(
                success=False,
                error_message="GEMINI_API_KEY not configured",
            )

        segments_summary = "\n".join(
            f"[{s.get('start_ms')}ms] {s.get('summary', 'N/A')} (type: {s.get('screen_type')}, value: {s.get('knowledge_value')})"
            for s in processed_segments[:20]
        )

        prompt = f"""
Synthesize a high-level session summary from this screen recording (asset: {asset_title}, duration: {duration_ms}ms).

SEGMENTS ({len(processed_segments)} total):
{segments_summary}

Analyze the workflow, identify problems, solutions, and key learning moments from the session.
"""

        try:
            model = genai.GenerativeModel(self.SYNTHESIS_MODEL)
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.5,
                    max_output_tokens=1500,
                    response_schema=SessionSynthesisResponse.model_json_schema(),
                    response_mime_type="application/json",
                ),
            )

            # Response is already in JSON format
            parsed = json.loads(response.text)

            # Estimate tokens
            prompt_tokens = len(prompt) // 4
            response_tokens = len(response.text) // 4
            total_tokens = prompt_tokens + response_tokens
            cost = (prompt_tokens * 0.075 + response_tokens * 0.30) / 1_000_000

            return LLMResult(
                success=True,
                parsed_data=parsed,
                tokens_used=total_tokens,
                cost_usd=cost,
            )

        except Exception as e:
            logger.exception(f"Session synthesis failed: {e}")
            return LLMResult(
                success=False,
                error_message=str(e),
            )


# Singleton instance
gemini_service = GeminiProcessingService()
