"""Ask user choice tool — asks the user one or more multiple-choice
questions through the chat UI instead of plain text, so the user can answer
by picking instead of typing.

Purely a UI handoff: nothing is created or mutated, no CommandRegistry
involved. The handler just echoes the questions back so agent_service can
stream them to the frontend as an `ask_choice` event, which renders a card
the user answers directly in. Unlike propose_plan this has no DB-backed
proposal — the answer flows straight back into the conversation as the
user's next chat message.
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.ai.agents.tool_context import ToolContext
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AskChoiceOptionInput(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=300)


class AskChoiceQuestionInput(BaseModel):
    id: str = Field(..., min_length=1, max_length=50, description="Local id you invent, e.g. 'q1'")
    question: str = Field(..., min_length=1, max_length=500)
    options: list[AskChoiceOptionInput] = Field(..., min_length=2, max_length=6)
    allow_multiple: bool = Field(default=False, description="Whether more than one option can be picked for this question")


class AskUserChoiceInput(BaseModel):
    questions: list[AskChoiceQuestionInput] = Field(..., min_length=1, max_length=4)


async def ask_user_choice_handler(args: dict, ctx: ToolContext) -> dict:
    """Hand the questions straight back — the frontend renders them, the
    user's picks come back as their next chat message. Nothing to persist."""
    return {"questions": args["questions"], "success": True}


ASK_USER_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "description": "One or more questions to ask the user, each with a fixed set of answer options. Call this once with all questions you need answered right now.",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Local id you invent, e.g. 'q1'"},
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "description": "2-6 sensible answer options. The UI always also lets the user type their own free-text answer, so don't add a generic 'other/khác' option yourself.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "description": {"type": "string", "description": "Optional short clarifying note shown under the option"},
                            },
                            "required": ["label"],
                        },
                    },
                    "allow_multiple": {"type": "boolean", "default": False, "description": "Set true if more than one option can be selected for this question"},
                },
                "required": ["id", "question", "options"],
            },
        },
    },
    "required": ["questions"],
}

ASK_USER_CHOICE_DEFINITION = {
    "name": "ask_user_choice",
    "handler": ask_user_choice_handler,
    "input_model": AskUserChoiceInput,
    "schema": ASK_USER_CHOICE_SCHEMA,
    "description": (
        "Ask the user one or more questions that have a small set of sensible answers, so they "
        "can answer by picking a button instead of typing — use this instead of asking as plain "
        "text whenever the possible answers are enumerable (e.g. picking between a few dates, "
        "confirming yes/no, choosing a category). The user can always type a custom answer too, "
        "so don't add a generic 'other' option yourself. This tool has no follow-up step and "
        "nothing is created — after calling it, do not call any other tool this turn; just stop "
        "and let the user answer. Do not use this for open-ended questions with no natural short "
        "list of answers."
    ),
}
