"""
Tests for Issue 1: extract_memory tool description and system prompt must
include explicit MUST-call triggers, since empirically LLM only called it
3.41% of the time.

These tests are static-text assertions (no LLM call) to verify the description
itself contains the required trigger signals and is referenced from the
system prompt.
"""
import os
import re


REPO_BACKEND = os.path.dirname(os.path.abspath(__file__))
TOOL_FILE = os.path.join(REPO_BACKEND, "app", "ai", "tools", "extract_memory.py")
SYSTEM_PROMPT_FILE = os.path.join(
    REPO_BACKEND, "app", "ai", "prompts", "system", "assistant_system.md"
)


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_definition_block(text):
    """Find the EXTRACT_MEMORY_DEFINITION = {...} block and return its raw content."""
    m = re.search(r"EXTRACT_MEMORY_DEFINITION\s*=\s*\{", text)
    if not m:
        return ""
    start = m.start()
    rest = text[start:]
    depth = 0
    i = 0
    in_string = False
    while i < len(rest):
        c = rest[i]
        if c == '"' and (i == 0 or rest[i - 1] != "\\"):
            in_string = not in_string
        if not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return rest[: i + 1]
        i += 1
    return ""


def test_tool_description_contains_must_call_triggers():
    """The tool description must list specific triggers that compel the LLM to call it."""
    text = load(TOOL_FILE)
    block = extract_definition_block(text)
    assert block, "EXTRACT_MEMORY_DEFINITION block not found"

    triggers = [
        "MUST be called",
        "references a prior conversation",
        "yesterday",
        "as I mentioned",
        "lần trước",
        "như đã nói",
        "preference",
        "last 10 messages",
        "long-term memory",
    ]
    missing = [t for t in triggers if t not in block]
    assert not missing, f"Description missing required trigger phrases: {missing}"


def test_tool_description_preserves_technical_explanation():
    """Original technical capabilities must still be present."""
    text = load(TOOL_FILE)
    block = extract_definition_block(text)
    technical_phrases = [
        "semantic memory graph",
        "episodic summary",
    ]
    missing = [p for p in technical_phrases if p not in block]
    assert not missing, f"Technical description missing: {missing}"


def test_system_prompt_has_must_call_section():
    """The MEMORY & CONTEXT block must contain a MUST-call instruction for extract_memory."""
    text = load(SYSTEM_PROMPT_FILE)

    assert "## MEMORY & CONTEXT" in text
    memory_section = text.split("## MEMORY & CONTEXT", 1)[1].split("## ", 1)[0]
    assert "extract_memory" in memory_section
    assert "MUST" in memory_section.upper(), "MUST-call instruction missing in MEMORY & CONTEXT"
    assert "last 10 messages" in memory_section, "Reference to 10-message window missing"


def test_system_prompt_preserves_mutating_action_rule():
    """Original mutating-action rule must remain untouched in MEMORY & CONTEXT."""
    text = load(SYSTEM_PROMPT_FILE)
    memory_section = text.split("## MEMORY & CONTEXT", 1)[1].split("## ", 1)[0]
    must_keep = [
        "Only perform mutating actions requested or clearly implied",
        "you MAY use previous conversation context",
        "you MAY use existing notes/schedules",
        "you MAY use inferred long-term goals",
    ]
    missing = [p for p in must_keep if p not in memory_section]
    assert not missing, f"Mutating-action rules removed/regressed: {missing}"


def test_system_prompt_preserves_vietnamese_triggers():
    """Vietnamese relative-time phrases from real user traffic must appear in the prompt."""
    text = load(SYSTEM_PROMPT_FILE)
    memory_section = text.split("## MEMORY & CONTEXT", 1)[1].split("## ", 1)[0]
    phrases = ["lần trước", "như đã nói"]
    missing = [p for p in phrases if p not in memory_section]
    assert not missing, f"Vietnamese trigger phrases missing: {missing}"


if __name__ == "__main__":
    test_tool_description_contains_must_call_triggers()
    test_tool_description_preserves_technical_explanation()
    test_system_prompt_has_must_call_section()
    test_system_prompt_preserves_mutating_action_rule()
    test_system_prompt_preserves_vietnamese_triggers()
    print("All Issue-1 tests passed.")
