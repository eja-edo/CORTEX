from dataclasses import dataclass, field
from typing import Any

from cortex_leads.core.errors import CortexError


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    # Set when the model emitted arguments that are not a JSON object; the runner
    # reports it back to the model instead of crashing.
    parse_error: str | None = None


@dataclass
class LLMResult:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


class LLMError(CortexError):
    """Base for gateway failures."""


class LLMTransientError(LLMError):
    """Worth another attempt (connection drop, 5xx, timeout)."""


class LLMFatalError(LLMError):
    """Auth / not-found / bad request: retrying cannot help."""


class LLMQuotaError(LLMError):
    """429 / quota: retrying immediately makes it worse (DESIGN §5.10)."""


class LLMTimeoutError(LLMTransientError):
    pass


class ShapeError(LLMError):
    """The model's text is not the JSON object we asked for."""


class ScriptExhaustedError(LLMError):
    """FakeProvider was called more times than its script allows."""
