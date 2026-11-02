"""How the AI introduces itself to a customer (Luật AI 134/2025, A9). The owner may give it a name (WP39); the line always starts with
"Trợ lý AI", so no name can make a customer think they are talking to a person."""
import re

AI_NAME = re.compile(r"^[\w .'\-]{1,40}$")  # letters (Vietnamese too), digits, space and . ' - : no links, no line breaks


def clean_ai_name(raw: str | None) -> str | None:
    """The name to keep, None for "none"; ValueError when it is not an acceptable name."""
    if any(ord(c) < 32 for c in raw or ""):  # a line break or tab is never part of a name; refuse rather than quietly join the lines
        raise ValueError("ai_name")
    name = " ".join((raw or "").split())
    if not name:
        return None
    if not AI_NAME.match(name):
        raise ValueError("ai_name")
    return name


def ai_disclosure(business_name: str, ai_name: str | None = None) -> str:
    """"Trợ lý AI Mai của Trung tâm ABC" / "Trợ lý AI của Trung tâm ABC"."""
    return f"Trợ lý AI {ai_name} của {business_name}" if ai_name else f"Trợ lý AI của {business_name}"
