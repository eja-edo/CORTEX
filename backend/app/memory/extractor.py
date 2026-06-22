import json
import logging
from typing import List, Dict, Any, Optional

from google import genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

_client = genai.Client(api_key=settings.GEMINI_API_KEY)

EXTRACTION_PROMPT = """You are a memory extraction engine. Given a user message, extract structured facts.

Return a JSON array of extracted memories. Each item has:
- "type": one of "preference", "tech_stack", "goal", "identity", "deadline", "relationship"
- "subject": short label (max 50 chars, English or Vietnamese)
- "value": the fact (max 200 chars)
- "importance": float 0.0-1.0 (how important is this to remember)
- "confidence": float 0.0-1.0 (how certain are you about this extraction)

Rules:
1. Only extract explicit, clearly stated facts. Do not infer or guess.
2. "preference": tools, languages, editors, workflows the user likes or dislikes
3. "tech_stack": specific technologies, frameworks, platforms being used
4. "goal": projects, features, systems the user is building
5. "identity": role, title, experience level, professional background
6. "deadline": time-bound commitments, due dates, release targets
7. "relationship": people, roles, teams the user works with
8. If nothing to extract, return empty array []
9. Be conservative — better to miss than to create garbage.

Message:
{message}

Return ONLY the JSON array, no explanation."""


class LLMExtractor:
    """
    LLM-based extraction — called from RQ worker for each detected message.
    """

    MODEL = "gemini-2.0-flash-001"

    def extract(self, message: str, signals: List[str]) -> List[Dict[str, Any]]:
        if not message or not message.strip():
            return []

        prompt = EXTRACTION_PROMPT.format(message=message[:2000])

        try:
            response = _client.models.generate_content(
                model=self.MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=1024,
                ),
            )

            if not response or not response.text:
                return []

            text = response.text.strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            result = json.loads(text)

            if not isinstance(result, list):
                return []

            filtered = [
                item for item in result
                if isinstance(item, dict)
                and item.get("type") in signals
                and item.get("subject")
                and item.get("value")
            ]

            return filtered

        except json.JSONDecodeError as e:
            logger.warning("Extraction JSON parse failed: %s", e)
            return []
        except Exception as e:
            logger.error("Extraction LLM call failed: %s", e, exc_info=True)
            return []
