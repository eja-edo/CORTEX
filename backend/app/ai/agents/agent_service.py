"""Main agent service for handling conversational AI requests with tool calling."""

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import AgentChatRequest as ChatRequest
from app.ai.agents.conversation_store import ConversationStore
from app.ai.agents.conversation_summarizer import get_conversation_summarizer
from app.ai.agents.model_client import (
    ModelClient,
    AllModelsExhaustedError,
    is_quota_error,
    is_fatal_error,
    is_model_incompatible_error,
    get_default_model,
)
from app.ai.agents.provider_types import (
    Message,
    GenerationConfig,
    ToolCall,
    ToolResult,
)
from app.ai.agents.tool_context import ToolContext
from app.ai.agents.tool_registry import get_tool_registry
from app.database_async import AsyncSessionLocal as DBAsyncSessionLocal
from app.utils.logger import get_logger
from app.ai.loaders.prompt_loader import load

logger = get_logger(__name__)

# System prompt that prevents tool hallucination and sets context
SYSTEM_PROMPT = load("system/assistant_system.md")


MAX_CONVERSATION_HISTORY = 10  # Load last N messages for context
MAX_TOOL_TURNS = 12             # Prevent infinite tool loops
MAX_SAME_TOOL_CALLS = 2        # Max times the same tool can be called per turn
MAX_TOKENS_PER_DAY_PER_USER = 100_000  # Daily token budget

# How many times to retry a single streaming turn on recoverable errors
# before giving up and yielding an error event to the client.
# Note: model_client.stream_with_fallback has its own internal rotation retries;
# this is a higher-level retry at the agent turn level.
MAX_TURN_RETRIES = 2

# Module-level ModelClient — one round-robin cursor shared across all
# AgentService instances so load is spread across models process-wide.
_model_client = ModelClient()


def _validate_contents_ordering(messages: list[Message]) -> tuple[bool, str]:
    if not messages:
        return True, "Messages array is empty"

    prev_role = None
    for i, msg in enumerate(messages):
        curr_role = msg.role

        if prev_role is not None and prev_role == curr_role:
            return False, (
                f"Role violation at index {i}: two consecutive '{curr_role}' roles. "
                f"Expected alternation: user\u2192model\u2192user\u2192model..."
            )

        if curr_role == "tool":
            if prev_role != "assistant":
                return False, (
                    f"Tool message at index {i} without preceding assistant. "
                    f"tool messages must follow an assistant response."
                )

        if msg.tool_calls and curr_role != "assistant":
            return False, (
                f"Tool calls at index {i} in role '{curr_role}'. "
                f"tool_calls must be in 'assistant' role."
            )

        if msg.tool_result and curr_role != "tool":
            return False, (
                f"Tool result at index {i} in role '{curr_role}'. "
                f"tool_result must be in 'tool' role."
            )

        prev_role = curr_role

    return True, f"Messages ordering valid ({len(messages)} items)"


def _log_contents_structure(messages: list[Message], label: str = "Messages") -> None:
    if not messages:
        logger.info(f"{label}: empty")
        return

    structure = []
    for i, msg in enumerate(messages):
        parts_info = [f"role={msg.role}"]
        if msg.content:
            parts_info.append(f"text[{len(msg.content)} chars]")
        if msg.tool_calls:
            for tc in msg.tool_calls:
                parts_info.append(f"tool_call[{tc.name}]")
        if msg.tool_result:
            parts_info.append(f"tool_result[{msg.tool_result.name}]")
        structure.append(f"[{i}] " + ", ".join(parts_info))

    logger.info(f"{label} ({len(messages)} items):\n  " + "\n  ".join(structure))


def _message_has_function_call(msg: Message) -> bool:
    return bool(msg.tool_calls)


def _trim_incomplete_tail(messages: list[Message], label: str) -> None:
    removed = 0
    while messages and messages[-1].role in ("user", "tool"):
        messages.pop()
        removed += 1
        if messages and messages[-1].role == "assistant" and _message_has_function_call(messages[-1]):
            messages.pop()
            removed += 1
    if removed:
        logger.info(
            f"Trimmed {removed} trailing history item(s) before appending current user ({label})"
        )


def _message_full_text(msg) -> str:
    """
    Reconstruct full message text from stored content + context.
    
    For user messages with structured context (pills, runtime info), combines
    them back together for LLM consumption. For messages without context
    (backward compatible), returns content as-is.
    """
    content = getattr(msg, 'content', '') or ''
    ctx = getattr(msg, 'context', None)
    
    if not ctx:
        return content
    
    parts = []
    pills = ctx.get('pills', [])
    runtime = ctx.get('runtime', None)
    
    if pills:
        pills_text = '\n\n---\n\n'.join(p['text'] for p in pills if p.get('text'))
        parts.append(f"Context:\n\n{pills_text}")
    if runtime:
        if isinstance(runtime, dict):
            runtime_lines = [f"{k}: {v}" for k, v in runtime.items() if v]
            parts.append(f"Runtime UI Context:\n\n" + '\n'.join(runtime_lines))
        else:
            parts.append(f"Runtime UI Context:\n\n{runtime}")
    
    if parts:
        return '\n\n'.join(parts) + f"\n\n{content}"
    return content


def _build_history_contents(records: list) -> list[Message]:
    """
    Convert stored AgentMessage records into internal Message objects.

    Ordering logic:
        - Enforces strict user → assistant → user → assistant alternation
        - Skips out-of-order messages
        - Tool messages emit (assistant with tool_calls) + (tool result) pair
        - Strips leading non-user records (dangling mid-turn tool/assistant
          when the conversation window starts mid-conversation)
    """
    # Strip leading non-user records — a valid conversation always starts with user
    records = list(records)
    while records and records[0].role != "user":
        records.pop(0)

    if not records:
        return []

    messages: list[Message] = []
    expected_role = "user"

    for record in records:
        role = getattr(record, 'role', None)
        content = getattr(record, 'content', None)
        tool_name = getattr(record, 'tool_name', None)
        tool_input = getattr(record, 'tool_input', None)
        tool_output = getattr(record, 'tool_output', None)

        if role == "user":
            user_text = _message_full_text(record)
            if not user_text:
                continue
            if expected_role != "user":
                logger.info(f"Skipping out-of-order user message (expected {expected_role})")
                continue
            messages.append(Message(role="user", content=user_text))
            expected_role = "assistant"

        elif role == "assistant":
            if expected_role != "assistant":
                logger.info(f"Skipping out-of-order assistant message (expected {expected_role})")
                continue
            if not content:
                logger.info(f"Skipping empty assistant message (content is {content!r})")
                continue
            messages.append(Message(role="assistant", content=content))
            expected_role = "user"

        elif role == "tool":
            if not (tool_name and tool_input is not None and tool_output is not None):
                logger.info(
                    f"Skipping incomplete tool message: tool_name={tool_name}, "
                    f"input_present={tool_input is not None}, output_present={tool_output is not None}"
                )
                continue

            if expected_role != "assistant":
                logger.info(f"Skipping out-of-order tool message (expected {expected_role})")
                continue

            messages.append(
                Message(
                    role="assistant",
                    tool_calls=[ToolCall(id=tool_name, name=tool_name, args=tool_input or {})],
                )
            )
            messages.append(
                Message(
                    role="tool",
                    tool_result=ToolResult(
                        tool_call_id=tool_name,
                        name=tool_name,
                        content=tool_output or {},
                    ),
                )
            )
            expected_role = "assistant"
        else:
            logger.info(f"Skipping unknown role message: {role}")

    return messages


class AgentService:
    """Orchestrates conversational AI agent interactions with tool calling."""

    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
        self.store = ConversationStore(db)
        self.registry = get_tool_registry()

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    async def _generate_conversation_title(self, message: str) -> str:
        try:
            prompt = f"""Generate a very short conversation title (max 10 words) based on this message:

"{message}"

Return ONLY the title, no quotes or explanation."""

            messages = [
                Message(role="user", content=prompt),
            ]

            gen_config = GenerationConfig(
                system_instruction="You are a helpful assistant that creates concise, descriptive conversation titles.",
                temperature=0.7,
            )

            logger.info(f"Generating title for new conversation...")
            model_used, response = await _model_client.generate(
                messages,
                gen_config,
                estimated_tokens=100,
            )

            title = response.content.strip() if response and response.content else ""

            title = title.strip('"\'')
            if len(title) > 100:
                title = title[:97] + "..."

            if not title:
                raise ValueError("Generated empty title")

            logger.info(f"Generated title: {title}")
            return title

        except Exception as exc:
            logger.warning(f"Failed to generate title (non-fatal): {exc}")
            words = message.split()[:5]
            fallback_title = " ".join(words) if words else "New Conversation"
            if len(fallback_title) > 100:
                fallback_title = fallback_title[:97] + "..."
            return fallback_title

    # ------------------------------------------------------------------
    # Non-streaming handle (unchanged logic, kept for completeness)
    # ------------------------------------------------------------------

    async def handle(
        self,
        message: str,
        conversation_id: UUID | None = None,
        workspace_id: UUID | None = None,
        context: dict | None = None,
    ) -> dict:
        """
        Process a user message with tool calling support and memory management.
        """
        try:
            if conversation_id:
                conv = await self.store.get_conversation_by_id(conversation_id, self.user.id)
                if not conv:
                    logger.warning(
                        f"Conversation not found for user {self.user.id}: {conversation_id}"
                    )
                    return {
                        "conversation_id": str(conversation_id),
                        "reply": "Conversation not found. Please start a new chat.",
                    }
            else:
                conv = await self.store.get_or_create_conversation(
                    user_id=self.user.id,
                    conversation_id=None,
                    workspace_id=workspace_id,
                )
        except Exception as exc:
            logger.error(f"Error getting conversation: {exc}", exc_info=True)
            raise

        if conv.total_token_count and conv.total_token_count >= MAX_TOKENS_PER_DAY_PER_USER:
            logger.warning(
                f"❌ User {self.user.id} exceeded daily token budget | "
                f"used={conv.total_token_count}/{MAX_TOKENS_PER_DAY_PER_USER}"
            )
            return {
                "conversation_id": str(conv.id),
                "reply": "You have reached your daily AI interaction limit. Please try again tomorrow.",
            }

        try:
            summarizer = get_conversation_summarizer(self.db)
        except Exception as exc:
            logger.warning(f"Error creating summarizer (non-fatal): {exc}")
            summarizer = None

        system_prompt = SYSTEM_PROMPT
        if summarizer and conv.summary:
            try:
                summary_context = await summarizer.get_conversation_context(
                    conv.id, include_summary=True
                )
                if summary_context:
                    system_prompt = (
                        f"{SYSTEM_PROMPT}\n\n"
                        f"=== PREVIOUS CONVERSATION CONTEXT ===\n{summary_context}"
                    )
            except Exception as exc:
                logger.warning(f"Error getting summary context: {exc}"        )

        recent_messages = await self.store.get_recent_messages(
            conv.id, limit=MAX_CONVERSATION_HISTORY
        )
        logger.info(
            f"📜 Loaded {len(recent_messages)} historical messages for conversation {conv.id}"
        )

        # Debug: Log raw message structure from DB
        if recent_messages:
            msg_summary = []
            for i, msg in enumerate(recent_messages):
                role = getattr(msg, 'role', 'unknown')
                tool_name = getattr(msg, 'tool_name', None)
                has_content = bool(getattr(msg, 'content', None))
                has_tool_input = bool(getattr(msg, 'tool_input', None) is not None)
                has_tool_output = bool(getattr(msg, 'tool_output', None) is not None)
                msg_summary.append(
                    f"[{i}] role={role} content={has_content} "
                    f"tool_name={tool_name} input={has_tool_input} output={has_tool_output}"
                )
            logger.info(f"📨 Raw DB messages:\n  " + "\n  ".join(msg_summary))

        await self.store.save_message(
            conversation_id=conv.id,
            role="user",
            content=message,
            context=context,
        )
        await self.store.increment_message_count(conv.id)

        tools = self.registry.get_provider_tools()
        gen_config = GenerationConfig(
            system_instruction=system_prompt,
        )

        tool_names = [t.name for t in tools]
        logger.info(f"Available tools: {tool_names if tool_names else 'None'}")

        try:
            ctx = ToolContext(
                user_id=self.user.id,
                async_db=self.db,
                workspace_id=workspace_id,
                conversation_id=conv.id,
            )

            turn = 0
            reply_text = None
            tool_call_counts: dict[str, int] = {}
            tool_call_id_counter = 0

            messages = _build_history_contents(recent_messages)
            _trim_incomplete_tail(messages, "handle")
            messages.append(Message(role="user", content=message))
            logger.info(
                f"Messages seeded with {len(messages)} items "
                f"({len(recent_messages)} history + 1 current)"
            )

            is_valid, validation_msg = _validate_contents_ordering(messages)
            logger.info(validation_msg)
            if not is_valid:
                logger.error(f"Messages ordering validation failed before first turn")
                _log_contents_structure(messages, "Invalid messages")
                raise ValueError(f"Invalid messages structure: {validation_msg}")
            _log_contents_structure(messages, "Valid messages for turn 1")

            while turn < MAX_TOOL_TURNS:
                logger.debug(f"Agent turn {turn + 1}/{MAX_TOOL_TURNS} | conversation={conv.id}")

                try:
                    _model_used, response = await _model_client.generate(
                        messages, gen_config, tools=tools,
                    )
                except AllModelsExhaustedError as api_error:
                    logger.warning(f"All models rate-limited: {str(api_error)[:200]}")
                    reply_text = (
                        "All AI models are currently rate-limited. "
                        "Please wait a moment and try again."
                    )
                    break
                except Exception as api_error:
                    error_str = str(api_error)
                    if is_fatal_error(api_error):
                        logger.error(f"Fatal API error: {error_str[:300]}", exc_info=True)
                        reply_text = (
                            "There was a configuration error. "
                            "Please contact support if this persists."
                        )
                    else:
                        logger.error(f"API error after retries: {error_str[:300]}", exc_info=True)
                        reply_text = "I encountered an error processing your request. Please try again."
                    break

                if not response:
                    logger.warning("API returned empty response")
                    reply_text = "I'm unable to generate a response at this time."
                    break

                tool_calls = response.tool_calls or []

                if not tool_calls:
                    reply_text = response.content or "I couldn't process your request."
                    logger.info(f"Agent finished at turn {turn + 1} (no tool calls)")
                    break

                if response.content:
                    await self.store.save_message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=response.content,
                    )

                messages.append(
                    Message(
                        role="assistant",
                        tool_calls=[
                            ToolCall(id=tc.id, name=tc.name, args=tc.args)
                            for tc in tool_calls
                        ],
                    )
                )

                is_valid, validation_msg = _validate_contents_ordering(messages)
                if not is_valid:
                    logger.error(f"Messages invalid after assistant tool_calls at turn {turn + 1}: {validation_msg}")
                    raise ValueError(f"Invalid messages structure: {validation_msg}")

                tool_results: list[Message] = []

                for tc in tool_calls:
                    tool_name = tc.name
                    if not tool_name:
                        logger.warning(f"Skipping tool call with empty name (id={tc.id})")
                        continue
                    tool_args = tc.args

                    tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
                    if tool_call_counts[tool_name] > MAX_SAME_TOOL_CALLS:
                        logger.warning(
                            f"Tool '{tool_name}' called {tool_call_counts[tool_name]} times "
                            f"in one turn — breaking loop"
                        )
                        reply_text = (
                            "I wasn't able to find the information you requested. "
                            "Could you provide more details?"
                        )
                        turn = MAX_TOOL_TURNS
                        break

                    logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
                    result = await self.registry.execute(tool_name, tool_args, ctx)
                    logger.info(f"Tool '{tool_name}' executed | result: {str(result)[:200]}")

                    await self._check_proactive_triggers(
                        tool_name=tool_name,
                        tool_result=result,
                        history=[],
                        ctx=ctx,
                    )

                    await self.store.save_message(
                        conversation_id=conv.id,
                        role="tool",
                        tool_name=tool_name,
                        tool_input=tool_args,
                        tool_output=result,
                    )

                    tool_results.append(
                        Message(
                            role="tool",
                            tool_result=ToolResult(
                                tool_call_id=tc.id,
                                name=tool_name,
                                content=result,
                            ),
                        )
                    )

                if tool_results:
                    messages.extend(tool_results)

                    is_valid, validation_msg = _validate_contents_ordering(messages)
                    if not is_valid:
                        logger.error(f"Messages invalid after appending tool responses at turn {turn + 1}: {validation_msg}")
                        _log_contents_structure(messages, "Invalid messages after tool responses")
                        raise ValueError(f"Invalid messages structure: {validation_msg}")

                if reply_text is not None:
                    break

                turn += 1

            if turn >= MAX_TOOL_TURNS and not reply_text:
                reply_text = (
                    "I reached my processing limit for this request. "
                    "Please try a simpler or more specific question."
                )
                logger.warning(f"Agent hit max turns ({MAX_TOOL_TURNS}) for conversation {conv.id}")

            if reply_text:
                await self.store.save_message(
                    conversation_id=conv.id,
                    role="assistant",
                    content=reply_text,
                )

            await self.store.update_conversation_timestamp(conv.id)
            await self.store.increment_message_count(conv.id)

            if (
                summarizer
                and conv.message_count >= summarizer.MESSAGE_THRESHOLD
                and conv.message_count % summarizer.MESSAGE_THRESHOLD < 2
            ):
                logger.info(f"💾 Triggering memory extraction | conversation={conv.id} | messages={conv.message_count}")
                try:
                    summary_result = await summarizer.summarize_conversation(conv.id)
                    if summary_result.get("success"):
                        logger.info(f"✅ Memory extraction complete | {summary_result}")
                    else:
                        logger.warning(f"⚠️ Memory extraction failed | {summary_result}")
                except Exception as exc:
                    logger.warning(f"Error in memory extraction: {exc}")

            await self.db.commit()

            return {
                "conversation_id": str(conv.id),
                "reply": reply_text or "No response generated.",
            }

        except Exception as exc:
            logger.error(f"❌ Error in agent loop: {exc}", exc_info=True)
            await self.db.rollback()
            raise
        finally:
            try:
                ctx.close()
            except Exception as close_error:
                logger.debug(f"Error closing context (non-fatal): {close_error}")

    # ------------------------------------------------------------------
    # Streaming handle (fixed)
    # ------------------------------------------------------------------

    async def handle_streaming_generator(
        self,
        message: str,
        conversation_id: UUID | None = None,
        workspace_id: UUID | None = None,
        context: dict | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ):
        """
        Process a user message with streaming response, yielding SSE events.

        Event types
        -----------
        title_generated — {"event": "title_generated", "conversation_id": str, "title": str}
        token           — {"event": "token",           "text": str}
        tool_start      — {"event": "tool_start",      "tool_name": str, "tool_args": dict}
        tool_result     — {"event": "tool_result",     "tool_name": str, "result": dict}
        error           — {"event": "error",           "message": str}
        done            — {"event": "done",            "conversation_id": str}

        Error handling
        --------------
        - AllModelsExhaustedError      → yield error event, break, commit what we have.
        - Fatal 4xx                    → yield error event, break.
        - Transient 5xx / format error → model_client buffers + retries internally
                                         across all models × STREAM_ROTATION_RETRIES,
                                         discarding the buffer each time.
                                         If still failing after all retries:
                                         yield error event, break.
        - Tool execution error         → yield error event, break (safe: DB not corrupt).
        - Max turns reached            → yield token with message + done event
                                         (not a hard error, but informs the user).
        """
        user_id = self.user.id
        conv = None
        ctx = None
        conversation_id_str = None  # Save early to avoid SQLAlchemy greenlet issues

        try:
            if conversation_id:
                conv = await self.store.get_conversation_by_id(conversation_id, user_id)
                if not conv:
                    logger.warning(
                        f"Conversation not found for user {user_id}: {conversation_id}"
                    )
                    yield {
                        "event": "error",
                        "message": "Conversation not found. Please start a new chat.",
                    }
                    return
            else:
                conv = await self.store.get_or_create_conversation(
                    user_id=user_id,
                    conversation_id=None,
                    workspace_id=workspace_id,
                )
                
                # Generate title for new conversation
                try:
                    new_title = await self._generate_conversation_title(message)
                    await self.store.update_conversation_title(conv.id, new_title)
                    conv.title = new_title
                    
                    # Notify frontend about the new title
                    yield {
                        "event": "title_generated",
                        "conversation_id": str(conv.id),
                        "title": new_title,
                    }
                    logger.info(f"✅ Generated and saved title for conversation {conv.id}: {new_title}")
                except Exception as exc:
                    logger.warning(f"⚠️ Title generation failed (non-fatal): {exc}")

            conversation_id_str = str(conv.id)  # Save conversation_id early

            # Check token budget
            if conv.total_token_count and conv.total_token_count >= MAX_TOKENS_PER_DAY_PER_USER:
                logger.warning(
                    f"❌ User {user_id} exceeded daily token budget in streaming | "
                    f"used={conv.total_token_count}/{MAX_TOKENS_PER_DAY_PER_USER}"
                )
                yield {
                    "event": "error",
                    "message": "You have reached your daily AI interaction limit. Please try again tomorrow.",
                }
                return

            summarizer = None
            try:
                summarizer = get_conversation_summarizer(self.db)
            except Exception as exc:
                logger.warning(f"Error creating summarizer (non-fatal): {exc}")

            # Load history BEFORE saving current message
            recent_messages = await self.store.get_recent_messages(
                conv.id, limit=MAX_CONVERSATION_HISTORY
            )
            logger.info(
                f"📜 Loaded {len(recent_messages)} historical messages for streaming conversation {conv.id}"
            )
            
            # Debug: Log raw message structure from DB
            if recent_messages:
                msg_summary = []
                for i, msg in enumerate(recent_messages):
                    role = getattr(msg, 'role', 'unknown')
                    tool_name = getattr(msg, 'tool_name', None)
                    has_content = bool(getattr(msg, 'content', None))
                    has_tool_input = bool(getattr(msg, 'tool_input', None) is not None)
                    has_tool_output = bool(getattr(msg, 'tool_output', None) is not None)
                    msg_summary.append(
                        f"[{i}] role={role} content={has_content} "
                        f"tool_name={tool_name} input={has_tool_input} output={has_tool_output}"
                    )
                logger.info(f"📨 Raw DB messages (streaming):\n  " + "\n  ".join(msg_summary))

            await self.store.save_message(
                conversation_id=conv.id,
                role="user",
                content=message,
                context=context,
            )
            await self.store.increment_message_count(conv.id)

            # Build system prompt with conversation memory
            system_prompt = SYSTEM_PROMPT
            if summarizer and conv.summary:
                try:
                    summary_context = await summarizer.get_conversation_context(
                        conv.id, include_summary=True
                    )
                    if summary_context:
                        system_prompt = (
                            f"{SYSTEM_PROMPT}\n\n"
                            f"=== PREVIOUS CONVERSATION CONTEXT ===\n{summary_context}"
                        )
                except Exception as exc:
                    logger.warning(f"Error getting summary context (streaming): {exc}")

            ctx = ToolContext(
                user_id=user_id,
                async_db=self.db,
                workspace_id=workspace_id,
                conversation_id=conv.id,
            )

            turn = 0
            reply_text = ""
            tool_call_counts: dict[str, int] = {}
            hard_error_occurred = False  # Track if we hit a hard error
            saved_assistant_count = 0
            total_usage: dict[str, int] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
            last_model_used: str | None = model

            messages = _build_history_contents(recent_messages)
            _trim_incomplete_tail(messages, "streaming")
            messages.append(Message(role="user", content=message))
            logger.info(
                f"Streaming messages seeded with {len(messages)} items "
                f"({len(recent_messages)} history + 1 current)"
            )

            is_valid, validation_msg = _validate_contents_ordering(messages)
            logger.info(validation_msg)
            if not is_valid:
                logger.error(f"Streaming: Messages ordering validation failed before first turn")
                try:
                    _log_contents_structure(messages, "Invalid streaming messages")
                except Exception as log_err:
                    logger.error(f"Error logging messages structure: {log_err}")
                yield {
                    "event": "error",
                    "message": "Internal error: Invalid conversation structure. Please start a new conversation.",
                }
                if conversation_id_str:
                    yield {"event": "done", "conversation_id": conversation_id_str}
                return
            _log_contents_structure(messages, "Valid streaming messages for turn 1")

            # User-selected model (None/"auto" → round-robin across all models)
            preferred_model = model if model and model != "auto" else None

            tools = self.registry.get_provider_tools()
            gen_config = GenerationConfig(
                system_instruction=system_prompt,
                temperature=temperature,
            )

            while turn < MAX_TOOL_TURNS:
                logger.debug(
                    f"Streaming turn {turn + 1}/{MAX_TOOL_TURNS} | conversation={conv.id}"
                )

                turn_text = ""
                tool_calls = []

                # ── Stream one turn with full fallback/retry ──────────────
                try:
                    async for chunk in _model_client.stream_with_fallback(
                        messages, gen_config, tools=tools,
                        preferred_model=preferred_model,
                    ):
                        if chunk.content:
                            turn_text += chunk.content
                            yield {"event": "token", "text": chunk.content}

                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)

                        if chunk.usage:
                            last_model_used = preferred_model or last_model_used
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                                total_usage[k] = total_usage.get(k, 0) + (chunk.usage.get(k) or 0)

                    # Stream completed successfully for this turn
                    reply_text += turn_text
                    logger.info(
                        f"Stream turn {turn + 1} complete | "
                        f"text_len={len(turn_text)} tool_calls={len(tool_calls)}"
                    )

                except AllModelsExhaustedError as exhausted_err:
                    logger.error(
                        f"❌ AllModelsExhaustedError at turn {turn + 1}: "
                        f"{str(exhausted_err)[:200]}"
                    )
                    yield {
                        "event": "error",
                        "message": "All AI models are currently busy. Please wait a moment and try again.",
                    }
                    hard_error_occurred = True
                    break

                except Exception as stream_err:
                    err_str = str(stream_err)
                    logger.error(
                        f"❌ Streaming error at turn {turn + 1} after all retries: "
                        f"{err_str[:300]}",
                        exc_info=True,
                    )

                    # Classify for a more helpful message
                    if is_fatal_error(stream_err):
                        user_msg = (
                            "There was a configuration error with the AI service. "
                            "Please contact support if this persists."
                        )
                    elif is_quota_error(stream_err):
                        user_msg = (
                            "The AI service is currently rate-limited. "
                            "Please wait a moment and try again."
                        )
                    elif is_model_incompatible_error(stream_err):
                        user_msg = (
                            "None of the available AI models could process this request. "
                            "Please try rephrasing or simplifying your message."
                        )
                    else:
                        user_msg = (
                            "I encountered an error while generating a response. "
                            "Please try again."
                        )

                    yield {"event": "error", "message": user_msg}
                    hard_error_occurred = True
                    break

                # ── Save model response for this turn ────────────────────
                if turn_text:
                    try:
                        saved_msg = await self.store.save_message(
                            conversation_id=conv.id,
                            role="assistant",
                            content=turn_text,
                        )
                        if saved_msg is not None:
                            saved_assistant_count += 1
                    except Exception as save_err:
                        logger.warning(f"Could not save assistant message (non-fatal): {save_err}")

                # ── Append model turn to messages for next iteration ──────
                if tool_calls:
                    messages.append(
                        Message(
                            role="assistant",
                            tool_calls=[
                                ToolCall(id=tc.id, name=tc.name, args=tc.args)
                                for tc in tool_calls
                            ],
                        )
                    )
                elif turn_text:
                    messages.append(Message(role="assistant", content=turn_text))

                is_valid, validation_msg = _validate_contents_ordering(messages)
                if not is_valid:
                    logger.error(f"Messages invalid after appending model response at turn {turn + 1}: {validation_msg}")
                    _log_contents_structure(messages, f"Invalid after turn {turn + 1} model response")
                    yield {
                        "event": "error",
                        "message": "Internal error: Conversation structure became invalid. Please start a new conversation.",
                    }
                    hard_error_occurred = True
                    break

                # ── No tool calls → done ──────────────────────────────────
                if not tool_calls:
                    logger.info(f"Streaming finished at turn {turn + 1} (no tool calls)")
                    break

                # ── Execute tools ─────────────────────────────────────────
                should_break = False
                tool_result_messages: list[Message] = []

                for tc in tool_calls:
                    tool_name = tc.name
                    if not tool_name:
                        logger.warning(f"Streaming: skipping tool call with empty name (id={tc.id})")
                        continue
                    tool_args = tc.args

                    tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
                    if tool_call_counts[tool_name] > MAX_SAME_TOOL_CALLS:
                        logger.warning(
                            f"Streaming: tool '{tool_name}' called "
                            f"{tool_call_counts[tool_name]} times — breaking loop"
                        )
                        loop_break_text = (
                            "\n\nI wasn't able to find what you were looking for. "
                            "Could you provide more details?"
                        )
                        reply_text += loop_break_text
                        yield {"event": "token", "text": loop_break_text}
                        should_break = True
                        break

                    logger.info(f"Streaming tool: {tool_name} | args: {tool_args}")

                    yield {
                        "event": "tool_start",
                        "tool_name": tool_name,
                        "tool_args": tool_args,
                    }

                    try:
                        result = await self.registry.execute(tool_name, tool_args, ctx)
                    except Exception as tool_exc:
                        logger.error(
                            f"Tool '{tool_name}' raised exception: {tool_exc}",
                            exc_info=True,
                        )
                        yield {
                            "event": "error",
                            "message": f"Tool '{tool_name}' failed unexpectedly. Please try again.",
                        }
                        hard_error_occurred = True
                        should_break = True
                        break

                    yield {
                        "event": "tool_result",
                        "tool_name": tool_name,
                        "success": bool(result.get("success")),
                        "result": result.get("result"),
                        "error": result.get("error"),
                    }

                    try:
                        await self.store.save_message(
                            conversation_id=conv.id,
                            role="tool",
                            tool_name=tool_name,
                            tool_input=tool_args,
                            tool_output=result,
                        )
                    except Exception as save_err:
                        logger.warning(f"Could not save tool message (non-fatal): {save_err}")

                    tool_result_messages.append(
                        Message(
                            role="tool",
                            tool_result=ToolResult(
                                tool_call_id=tc.id,
                                name=tool_name,
                                content=result,
                            ),
                        )
                    )

                if tool_result_messages:
                    messages.extend(tool_result_messages)

                    is_valid, validation_msg = _validate_contents_ordering(messages)
                    if not is_valid:
                        logger.error(f"Messages invalid after appending tool responses at turn {turn + 1}: {validation_msg}")
                        _log_contents_structure(messages, "Invalid after tool responses")
                        yield {
                            "event": "error",
                            "message": "Internal error: Tool response created invalid conversation structure. Please try again.",
                        }
                        hard_error_occurred = True
                        should_break = True
                        break

                if should_break:
                    break

                turn += 1

            # ── Max turns reached without a reply ────────────────────────
            if turn >= MAX_TOOL_TURNS and not reply_text and not hard_error_occurred:
                limit_text = (
                    "I reached my processing limit for this request. "
                    "Please try a simpler or more specific question."
                )
                reply_text = limit_text
                yield {"event": "token", "text": limit_text}
                # Also surface as an error event so the FE knows this wasn't clean
                yield {
                    "event": "error",
                    "message": "Processing limit reached. Please simplify your request.",
                }
                logger.warning(
                    f"Streaming hit max turns ({MAX_TOOL_TURNS}) for conversation {conv.id}"
                )

            # ── Persist final assistant reply ─────────────────────────────
            if reply_text and saved_assistant_count == 0:
                try:
                    await self.store.save_message(
                        conversation_id=conv.id,
                        role="assistant",
                        content=reply_text,
                    )
                except Exception as save_err:
                    logger.warning(f"Could not save final reply (non-fatal): {save_err}")

            await self.store.update_conversation_timestamp(conv.id)
            await self.store.increment_message_count(conv.id)

            # Persist token usage for the daily budget / analytics
            if total_usage.get("total_tokens"):
                try:
                    await self.store.increment_token_count(
                        conv.id, total_usage["total_tokens"]
                    )
                except Exception as tok_err:
                    logger.warning(f"Could not record token count (non-fatal): {tok_err}")
                try:
                    _model_client.record_stream_tokens(
                        preferred_model or get_default_model(_model_client._provider),
                        total_usage["total_tokens"],
                    )
                except Exception:
                    pass

            # Trigger memory extraction if at threshold boundary
            if (
                summarizer
                and conv.message_count >= summarizer.MESSAGE_THRESHOLD
                and conv.message_count % summarizer.MESSAGE_THRESHOLD < 2
            ):
                logger.info(
                    f"💾 Triggering memory extraction (streaming) | conversation={conv.id} | messages={conv.message_count}"
                )
                try:
                    summary_result = await summarizer.summarize_conversation(conv.id)
                    if summary_result.get("success"):
                        logger.info(f"✅ Memory extraction complete (streaming) | {summary_result}")
                    else:
                        logger.warning(f"⚠️ Memory extraction failed (streaming) | {summary_result}")
                except Exception as exc:
                    logger.warning(f"Error in memory extraction (streaming): {exc}")

            await self.db.commit()

            # Always yield done — even after an error event — so the FE
            # can close the stream and get the conversation_id.
            if not conversation_id_str:
                conversation_id_str = str(conv.id)
            yield {
                "event": "done",
                "conversation_id": conversation_id_str,
                "usage": total_usage,
                "model_used": last_model_used or "auto",
            }
            logger.info(
                f"✅ Streaming completed | conversation={conversation_id_str} | "
                f"hard_error={hard_error_occurred} | usage={total_usage}"
            )

        except Exception as exc:
            logger.error(f"❌ Unhandled error in streaming generator: {exc}", exc_info=True)
            try:
                await self.db.rollback()
            except Exception as rollback_error:
                logger.debug(f"Error rolling back (non-fatal): {rollback_error}")

            yield {
                "event": "error",
                "message": "An unexpected error occurred while processing your request.",
            }
            # Still yield done so the FE can clean up
            if conversation_id_str:
                yield {"event": "done", "conversation_id": conversation_id_str}
            elif conv is not None:
                try:
                    yield {"event": "done", "conversation_id": str(conv.id)}
                except Exception as conv_id_err:
                    logger.debug(f"Could not access conv.id: {conv_id_err}")

        finally:
            if ctx is not None:
                try:
                    ctx.close()
                except Exception as close_error:
                    logger.debug(f"Error closing context (non-fatal): {close_error}")

    # ------------------------------------------------------------------
    # Proactive triggers (stubs)
    # ------------------------------------------------------------------

    async def _check_proactive_triggers(
        self,
        tool_name: str,
        tool_result: dict,
        history: list,
        ctx: ToolContext,
    ) -> None:
        try:
            if tool_name == "create_schedule":
                await self._check_schedule_conflicts(tool_result, history, ctx)
            elif tool_name == "create_note":
                await self._check_note_action_suggestions(tool_result, history, ctx)
            elif tool_name == "search_knowledge":
                await self._check_knowledge_suggestions(tool_result, history, ctx)
        except Exception as exc:
            logger.warning(f"Error in proactive trigger check: {exc}")

    async def _check_schedule_conflicts(
        self, tool_result: dict, history: list, ctx: ToolContext
    ) -> None:
        logger.debug("Checking for schedule conflicts...")

    async def _check_note_action_suggestions(
        self, tool_result: dict, history: list, ctx: ToolContext
    ) -> None:
        logger.debug("Checking for note action suggestions...")

    async def _check_knowledge_suggestions(
        self, tool_result: dict, history: list, ctx: ToolContext
    ) -> None:
        logger.debug("Checking for knowledge suggestions...")