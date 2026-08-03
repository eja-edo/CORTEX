"""Token estimation utilities for conversation history management.

Uses tiktoken when available for accurate counts, with fallback
to character-based estimation for unknown models.
"""

from app.utils.logger import get_logger

logger = get_logger(__name__)

CHARS_PER_TOKEN_ESTIMATE = 3.5

TOOL_TOKEN_WEIGHT = 0.25
TOOL_TOKEN_CAP = 800


def _get_encoding_name(model: str | None = None) -> str:
    if model and "gpt-4" in model:
        return "cl100k_base"
    if model and "gpt-3.5" in model:
        return "cl100k_base"
    return "cl100k_base"


_encoding = None


def _get_encoding():
    global _encoding
    if _encoding is not None:
        return _encoding
    try:
        import tiktoken
        _encoding = tiktoken.get_encoding(_get_encoding_name())
    except Exception as exc:
        logger.debug(f"tiktoken not available, using char estimate: {exc}")
        _encoding = None
    return _encoding


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in a text string.

    Uses tiktoken for accurate encoding if available,
    falls back to character-based estimation.
    """
    if not text:
        return 0

    enc = _get_encoding()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception as exc:
            logger.debug(f"tiktoken encoding failed, falling back to char estimate: {exc}")

    return max(1, int(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def estimate_message_tokens(role: str, content: str | None, tool_name: str | None = None, tool_output: dict | None = None) -> int:
    """Estimate tokens for a single conversation message record."""
    total = 0

    if content:
        total += estimate_tokens(content)

    total += estimate_tokens(role)

    if tool_name:
        total += estimate_tokens(tool_name)

    if tool_output:
        import json
        try:
            total += estimate_tokens(json.dumps(tool_output, default=str))
        except Exception:
            total += estimate_tokens(str(tool_output))

    total += 4
    return total


def estimate_weighted_message_tokens(role: str, content: str | None, tool_name: str | None = None, tool_output: dict | None = None) -> int:
    """Estimate tokens with tool weighting policy applied.

    User/assistant messages: full estimated token count (weight = 1.0).
    Tool messages: min(estimated_tokens * TOOL_WEIGHT, TOOL_TOKEN_CAP).

    This is the authoritative function for tokens_since_last_summary.
    """
    raw = estimate_message_tokens(role, content, tool_name, tool_output)
    if role == "tool":
        return min(int(raw * TOOL_TOKEN_WEIGHT), TOOL_TOKEN_CAP)
    return raw
