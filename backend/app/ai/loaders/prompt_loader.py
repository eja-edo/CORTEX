"""Prompt loader — loads prompt templates from ai/prompts/ directory."""

import os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load(path: str) -> str:
    """Load a prompt file from ai/prompts/{path}.

    Args:
        path: Relative path under prompts/, e.g. "system/assistant_system.md"

    Returns:
        The raw prompt text.
    """
    full_path = _PROMPTS_DIR / path
    return full_path.read_text(encoding="utf-8")


def render(path: str, **kwargs) -> str:
    """Load a prompt file and render it with str.format(**kwargs).

    Args:
        path: Relative path under prompts/.
        **kwargs: Variables to substitute into the template (uses {placeholder} syntax).

    Returns:
        The rendered prompt text.
    """
    text = load(path)
    if kwargs:
        text = text.format(**kwargs)
    return text
