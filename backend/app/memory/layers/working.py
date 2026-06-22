import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class WorkingMemory:
    """
    Layer 1: Working Memory
    Sliding window token-based, thay thế MAX_CONVERSATION_HISTORY = 10.
    """

    # Model token limits (conservative)
    MODEL_MAX_TOKENS = {
        "gemini-2.0-flash-001": 1_000_000,
        "gemini-1.5-flash-001": 1_000_000,
        "deepseek-chat": 64_000,
    }

    # Reserved tokens for system prompt and recent responses
    RESERVED_SYSTEM_TOKENS = 4_000
    RESERVED_OUTPUT_TOKENS = 2_000

    DEFAULT_MAX_TOKENS = 32_000

    def __init__(self, model_name: str = "gemini-2.0-flash-001"):
        self.model_name = model_name
        self.max_context = self.MODEL_MAX_TOKENS.get(model_name, self.DEFAULT_MAX_TOKENS)

    def get_available_tokens(self) -> int:
        return self.max_context - self.RESERVED_SYSTEM_TOKENS - self.RESERVED_OUTPUT_TOKENS

    def compute_window_tokens(self, messages: List[Dict[str, Any]]) -> int:
        return sum(m.get("token_count", 0) or len(m.get("parts", [{}])[0].get("text", "")) // 4 + 50 for m in messages)

    def trim_context(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        available = self.get_available_tokens()
        total = 0
        window = []

        for msg in reversed(messages):
            tokens = msg.get("token_count", 0) or len(msg.get("parts", [{}])[0].get("text", "")) // 4 + 50
            if total + tokens > available:
                break
            total += tokens
            window.append(msg)

        window.reverse()
        return window
