"""Main agent service — thin orchestrator delegating to ConversationService, ToolExecutionService, MemoryTriggerService."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import AsyncSessionLocal
from app.ids import uuid7
from app.models import User
from app.schemas import AgentChatRequest as ChatRequest
from app.ai.agents.conversation_service import ConversationService, _build_history_contents, _inject_context_into_text, _format_timestamp, _trim_incomplete_tail
from app.ai.agents.tool_execution_service import ToolExecutionService, _estimate_token_breakdown, _validate_contents_ordering, _log_contents_structure, MAX_TOOL_TURNS
from app.ai.agents.memory_trigger_service import MemoryTriggerService
from app.ai.agents.conversation_store import ConversationStore
from app.ai.agents.model_client import (
    ModelClient,
    is_fatal_error,
    is_quota_error,
    is_model_incompatible_error,
)
from app.ai.agents.provider_types import Message, GenerationConfig, ToolCall, ToolResult
from app.ai.agents.tool_context import ToolContext
from app.services.user_preferences import get_chat_model_async
from app.ai.agents.tool_registry import get_tool_registry
from app.config import settings
from app.utils.logger import get_logger
from app.ai.loaders.prompt_loader import load

logger = get_logger(__name__)

SYSTEM_PROMPT = load("system/assistant_system.md")

MAX_CONVERSATION_HISTORY = 10
MAX_TOOL_TURNS = 30
MAX_SAME_TOOL_CALLS = 20
MAX_TOKENS_PER_DAY_PER_USER = 2_000_000
MAX_TURN_RETRIES = 3

_model_client = ModelClient()


class AgentService:
    """Orchestrates conversational AI agent interactions — delegates to specialized services."""

    def __init__(self, user: User, db: AsyncSession):
        self.user = user
        self.db = db
        self.registry = get_tool_registry()
        initial_store = ConversationStore(db)
        self.conversation_service = ConversationService(user, db, store=initial_store)
        self.tool_service = ToolExecutionService(user, db, initial_store, self.registry)
        self.memory_service = MemoryTriggerService(db)

    @property
    def store(self):
        return self.conversation_service.store

    @store.setter
    def store(self, value):
        self.conversation_service.store = value
        self.tool_service.store = value

    async def _check_proactive_triggers(self, tool_name, tool_result, history, ctx):
        await self.tool_service._check_proactive_triggers(tool_name, tool_result, history, ctx)

    async def _check_schedule_conflicts(self, tool_result, history, ctx):
        await self.tool_service._check_schedule_conflicts(tool_result, history, ctx)

    async def _check_note_action_suggestions(self, tool_result, history, ctx):
        await self.tool_service._check_note_action_suggestions(tool_result, history, ctx)

    async def _check_knowledge_suggestions(self, tool_result, history, ctx):
        await self.tool_service._check_knowledge_suggestions(tool_result, history, ctx)

    def _detect_intent(self, message: str) -> str | None:
        """Milestone 1.8 (IntentDetectionService): L1 rule-based intent
        detection, used only to sharpen ContextService's relevance filter.
        Never raises, never changes tool-calling behavior — UNKNOWN/no-match
        falls through to the existing full loop exactly as before this
        milestone existed."""
        try:
            from app.intents.intent_service import get_intent_service
            from app.intents.schemas import IntentType
            detected = get_intent_service().detect(message)
            if detected.intent_type == IntentType.UNKNOWN:
                return None
            return detected.intent_type.value
        except Exception as exc:
            logger.warning(f"Intent detection failed (non-fatal): {exc}")
            return None

    async def _build_context_string(self, workspace_id: UUID | None, conv_id: UUID, context: dict | None, message: str = "") -> str | None:
        """Milestone 1.7 (ContextService): workspace/recent-notes/upcoming-
        schedules section appended to the system prompt. Never raises —
        this is an enrichment, not a requirement for the chat flow."""
        try:
            from app.context.context_service import ContextService
            context_service = ContextService(self.db)
            unified_context = await context_service.build_context(
                user_id=self.user.id,
                workspace_id=workspace_id,
                conversation_id=conv_id,
                runtime_context=context,
                intent=self._detect_intent(message),
            )
            return unified_context.to_llm_string()
        except Exception as exc:
            logger.warning(f"ContextService failed to build context (non-fatal): {exc}")
            return None

    async def handle(self, message: str, conversation_id: UUID | None = None, workspace_id: UUID | None = None, context: dict | None = None, model: str | None = None) -> dict:
        preferred_model = model if model and model != "auto" else None
        conv, title = await self.conversation_service.get_or_create(conversation_id, workspace_id, message)
        if conv is None:
            return {"conversation_id": str(conversation_id), "reply": title}

        budget_ok, budget_err = await self.conversation_service.check_token_budget(conv)
        if not budget_ok:
            return {"conversation_id": str(conv.id), "reply": budget_err}

        summarizer = await self.conversation_service.get_summarizer()
        recent_messages = await self.conversation_service.load_history(conv.id, conv.last_summary_message_id)
        self.conversation_service.log_raw_messages(recent_messages, "handle")

        context_string = await self._build_context_string(workspace_id, conv.id, context, message)
        system_prompt = await self.conversation_service.build_system_prompt(conv, message, context, summarizer, SYSTEM_PROMPT, context_string=context_string, recent_messages=recent_messages)

        await self.conversation_service.save_user_message(conv.id, message, context)
        await self.conversation_service.increment_message_count(conv.id)

        tools = self.registry.get_provider_tools()
        gen_config = GenerationConfig(system_instruction=system_prompt)
        logger.info(f"Available tools: {[t.name for t in tools] if tools else 'None'}")

        ctx = ToolContext(user_id=self.user.id, async_db=self.db, workspace_id=workspace_id, conversation_id=conv.id)

        messages = _build_history_contents(recent_messages)
        _trim_incomplete_tail(messages, "handle")
        now = datetime.utcnow()
        messages.append(Message(role="user", content=_format_timestamp(now) + _inject_context_into_text(message, context), created_at=now))
        logger.info(f"Messages seeded with {len(messages)} items ({len(recent_messages)} history + 1 current)")

        is_valid, validation_msg = _validate_contents_ordering(messages)
        logger.info(validation_msg)
        if not is_valid:
            logger.error(f"Messages ordering validation failed before first turn")
            _log_contents_structure(messages, "Invalid messages")
            raise ValueError(f"Invalid messages structure: {validation_msg}")
        _log_contents_structure(messages, "Valid messages for turn 1")

        total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_system_prompt_tokens": 0, "estimated_history_tokens": 0, "estimated_current_input_tokens": 0, "estimated_tool_results_tokens": 0}
        turn = 0
        reply_text = None
        tool_call_counts = {}
        _last_assistant_completion = 0
        source_id_counter = 0
        if settings.AGENT_TOOL_CALL_COUNT_SCOPE not in ("turn", "request"):
            logger.warning(f"Unknown AGENT_TOOL_CALL_COUNT_SCOPE='{settings.AGENT_TOOL_CALL_COUNT_SCOPE}'. Expected 'turn' or 'request'. Defaulting to 'request' behavior.")

        while turn < MAX_TOOL_TURNS:
            if settings.AGENT_TOOL_CALL_COUNT_SCOPE == "turn":
                tool_call_counts = {}
            logger.debug(f"Agent turn {turn + 1}/{MAX_TOOL_TURNS} | conversation={conv.id}")

            bd = _estimate_token_breakdown(messages, gen_config.system_instruction or "", turn)
            for k, v in bd.items():
                total_usage[k] = total_usage.get(k, 0) + v
            self.tool_service.log_token_breakdown(bd, turn, conv.id)

            try:
                _model_used, response = await _model_client.generate(messages, gen_config, tools=tools, preferred_model=preferred_model)
                if response and response.usage:
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_usage[k] = total_usage.get(k, 0) + (response.usage.get(k) or 0)
                    _last_assistant_completion = response.usage.get("completion_tokens", 0)
            except Exception as api_error:
                error_str = str(api_error)
                if is_fatal_error(api_error):
                    logger.error(f"Fatal API error: {error_str[:300]}", exc_info=True)
                    reply_text = "There was a configuration error. Please contact support if this persists."
                elif is_quota_error(api_error):
                    logger.warning(f"Model rate-limited: {error_str[:200]}")
                    reply_text = "The AI service is currently rate-limited. Please wait a moment and try again."
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

            messages.append(Message(role="assistant", tool_calls=[ToolCall(id=tc.id, name=tc.name, args=tc.args) for tc in tool_calls], created_at=datetime.utcnow()))
            is_valid, validation_msg = _validate_contents_ordering(messages)
            if not is_valid:
                logger.error(f"Messages invalid after assistant tool_calls at turn {turn + 1}: {validation_msg}")
                raise ValueError(f"Invalid messages structure: {validation_msg}")

            execution_list, should_break, limit_reply = await self.tool_service.check_tool_limits(tool_calls, tool_call_counts)

            if should_break:
                reply_text = limit_reply
                break

            tool_result_messages, exec_results, _, _, source_id_counter = await self.tool_service.execute_tools_pass(
                tool_calls, conv, ctx, turn, tool_call_counts, source_id_counter, workspace_id,
            )

            for _, tool_name, result in exec_results:
                await self._check_proactive_triggers(tool_name=tool_name, tool_result=result, history=[], ctx=ctx)

            if tool_result_messages:
                messages.extend(tool_result_messages)
                is_valid, validation_msg = _validate_contents_ordering(messages)
                if not is_valid:
                    logger.error(f"Messages invalid after appending tool responses at turn {turn + 1}: {validation_msg}")
                    _log_contents_structure(messages, "Invalid messages after tool responses")
                    raise ValueError(f"Invalid messages structure: {validation_msg}")

            turn += 1

        if turn >= MAX_TOOL_TURNS and not reply_text:
            logger.warning(f"event=max_tool_turns_hit turn_count={turn} conversation_id={conv.id}")
            logger.warning(f"Agent hit max turns ({MAX_TOOL_TURNS}) — attempting synthesis turn for conversation {conv.id}")
            try:
                synthesis_config = GenerationConfig(system_instruction=gen_config.system_instruction, temperature=gen_config.temperature)
                _, synthesis_response = await _model_client.generate(messages, synthesis_config, tools=None, preferred_model=preferred_model)
                reply_text = synthesis_response.content if synthesis_response and synthesis_response.content else "I reached my processing limit for this request. Please try a simpler or more specific question."
                if synthesis_response and synthesis_response.usage:
                    for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                        total_usage[k] = total_usage.get(k, 0) + (synthesis_response.usage.get(k) or 0)
                    _last_assistant_completion = synthesis_response.usage.get("completion_tokens", 0)
            except Exception as synth_exc:
                logger.warning(f"Synthesis turn failed (non-fatal): {synth_exc}")
                reply_text = "I reached my processing limit for this request. Please try a simpler or more specific question."

        if reply_text:
            await self.conversation_service.store.save_message(conversation_id=conv.id, role="assistant", content=reply_text, token_count=_last_assistant_completion or None)
        await self.conversation_service.update_timestamp(conv.id)
        await self.conversation_service.increment_message_count(conv.id)

        await self.memory_service.maybe_trigger(summarizer, conv)
        await self.db.commit()

        logger.info(f"event=token_breakdown_total estimated_system_prompt_tokens={total_usage['estimated_system_prompt_tokens']} estimated_history_tokens={total_usage['estimated_history_tokens']} estimated_current_input_tokens={total_usage['estimated_current_input_tokens']} estimated_tool_results_tokens={total_usage['estimated_tool_results_tokens']} prompt_tokens={total_usage['prompt_tokens']} completion_tokens={total_usage['completion_tokens']} total_tokens={total_usage['total_tokens']} conversation_id={conv.id}")

        result = {"conversation_id": str(conv.id), "reply": reply_text or "No response generated."}
        if title:
            result["title"] = title
        return result

    async def _resolve_preferred_model(self, model: str | None, surface: str | None, user_id) -> str | None:
        """Which model this turn should run on, or None for the default.

        The Mezon surface has no model dropdown — `*model` writes the
        choice to `user_preferences.chat_model` instead, and this is where
        it takes effect. Scoped to that surface deliberately: the web has
        its own picker, and letting a choice made in a DM override it
        would leave that dropdown describing a model that isn't running.
        A stored id that has since left the catalogue needs no special
        case — `ModelClient._resolve` falls back to the default for any
        unknown id.

        **The savepoint is the load-bearing part.** This session holds a
        transaction full of flushed-but-uncommitted rows (the user's
        message, assistant turns, tool results — `AgentService` commits
        once at the end), and a failed statement poisons the whole
        transaction: Postgres refuses every command after it with
        "current transaction is aborted". Catching the error is not
        enough, and a plain `rollback()` would throw the turn's own
        writes away. `begin_nested()` confines the damage to this read.

        That is not hypothetical — it is exactly how this failed the first
        time it ran: the column was missing on a database that had not
        been migrated, this read raised, the `except` below logged it as
        non-fatal, and the turn then died several statements later in
        `update_conversation_timestamp` with an error naming a table that
        had nothing to do with it.
        """
        if model and model != "auto":
            return model
        if surface != "mezon":
            return None

        try:
            async with self.db.begin_nested():
                return await get_chat_model_async(self.db, user_id)
        except Exception as pref_err:
            logger.warning(f"Could not read chat model preference (non-fatal): {pref_err}")
            return None

    async def handle_streaming_generator(self, message: str, conversation_id: UUID | None = None, workspace_id: UUID | None = None, context: dict | None = None, model: str | None = None, temperature: float | None = None, surface: str | None = None):
        user_id = self.user.id
        conv = None
        ctx = None
        conversation_id_str = None
        # None keeps every existing (web) call site byte-for-byte unchanged:
        # still create-a-new-conversation-every-time when no conversation_id
        # is given, and every saved row keeps source=NULL ("web" — see
        # `AgentMessage.source`'s docstring). Only surface="mezon" (the bot,
        # M3) resolves to a single long-running conversation instead — see
        # `get_or_create_mezon_conversation`'s docstring for why.
        message_source = "mezon" if surface == "mezon" else None

        try:
            if conversation_id:
                conv = await self.conversation_service.store.get_conversation_by_id(conversation_id, user_id)
                if not conv:
                    logger.warning(f"Conversation not found for user {user_id}: {conversation_id}")
                    yield {"event": "error", "message": "Conversation not found. Please start a new chat."}
                    return
            elif surface == "mezon":
                conv = await self.conversation_service.store.get_or_create_mezon_conversation(user_id)
            else:
                conv = await self.conversation_service.store.get_or_create_conversation(user_id=user_id, workspace_id=workspace_id)
                try:
                    new_title = await self.conversation_service._generate_conversation_title(message)
                    await self.conversation_service.store.update_conversation_title(conv.id, new_title)
                    conv.title = new_title
                    yield {"event": "title_generated", "conversation_id": str(conv.id), "title": new_title}
                    logger.info(f"Generated and saved title for conversation {conv.id}: {new_title}")
                except Exception as exc:
                    logger.warning(f"Title generation failed (non-fatal): {exc}")

            conversation_id_str = str(conv.id)

            budget_ok, budget_err = await self.conversation_service.check_token_budget(conv)
            if not budget_ok:
                yield {"event": "error", "message": budget_err}
                return

            summarizer = await self.conversation_service.get_summarizer()
            recent_messages = await self.conversation_service.load_history(conv.id, conv.last_summary_message_id)
            self.conversation_service.log_raw_messages(recent_messages, "streaming")

            await self.conversation_service.save_user_message(conv.id, message, context, source=message_source)
            await self.conversation_service.increment_message_count(conv.id)

            context_string = await self._build_context_string(workspace_id, conv.id, context, message)
            system_prompt = await self.conversation_service.build_system_prompt(conv, message, context, summarizer, SYSTEM_PROMPT, context_string=context_string, recent_messages=recent_messages)

            ctx = ToolContext(user_id=user_id, async_db=self.db, workspace_id=workspace_id, conversation_id=conv.id)

            tools = self.registry.get_provider_tools()
            gen_config = GenerationConfig(system_instruction=system_prompt, temperature=temperature)

            messages = _build_history_contents(recent_messages)
            _trim_incomplete_tail(messages, "streaming")
            now = datetime.utcnow()
            messages.append(Message(role="user", content=_format_timestamp(now) + _inject_context_into_text(message, context), created_at=now))
            logger.info(f"Streaming messages seeded with {len(messages)} items ({len(recent_messages)} history + 1 current)")

            is_valid, validation_msg = _validate_contents_ordering(messages)
            logger.info(validation_msg)
            if not is_valid:
                logger.error(f"Streaming: Messages ordering validation failed before first turn")
                yield {"event": "error", "message": "Internal error: Invalid conversation structure. Please start a new conversation."}
                if conversation_id_str:
                    yield {"event": "done", "conversation_id": conversation_id_str}
                return
            _log_contents_structure(messages, "Valid streaming messages for turn 1")

            preferred_model = await self._resolve_preferred_model(model, surface, user_id)
            turn = 0
            reply_text = ""
            tool_call_counts = {}
            source_id_counter = 0
            if settings.AGENT_TOOL_CALL_COUNT_SCOPE not in ("turn", "request"):
                logger.warning(f"Unknown AGENT_TOOL_CALL_COUNT_SCOPE='{settings.AGENT_TOOL_CALL_COUNT_SCOPE}'. Expected 'turn' or 'request'. Defaulting to 'request' behavior.")
            hard_error_occurred = False
            saved_assistant_count = 0
            total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "estimated_system_prompt_tokens": 0, "estimated_history_tokens": 0, "estimated_current_input_tokens": 0, "estimated_tool_results_tokens": 0}
            last_model_used = model

            while turn < MAX_TOOL_TURNS:
                if settings.AGENT_TOOL_CALL_COUNT_SCOPE == "turn":
                    tool_call_counts = {}
                logger.debug(f"Streaming turn {turn + 1}/{MAX_TOOL_TURNS} | conversation={conv.id}")

                bd = _estimate_token_breakdown(messages, gen_config.system_instruction or "", turn)
                for k, v in bd.items():
                    total_usage[k] = total_usage.get(k, 0) + v
                self.tool_service.log_token_breakdown(bd, turn, conv.id)

                turn_text = ""
                tool_calls = []
                _turn_completion_before = total_usage.get("completion_tokens", 0)
                _turn_completion = 0

                try:
                    async for chunk in _model_client.stream(messages, gen_config, tools=tools, preferred_model=preferred_model):
                        if chunk.content:
                            turn_text += chunk.content
                            yield {"event": "token", "text": chunk.content}
                        if chunk.reasoning:
                            yield {"event": "reasoning_token", "text": chunk.reasoning}
                        if chunk.tool_calls:
                            tool_calls.extend(chunk.tool_calls)
                        if chunk.usage:
                            last_model_used = preferred_model or last_model_used
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                                total_usage[k] = total_usage.get(k, 0) + (chunk.usage.get(k) or 0)

                    _turn_completion = total_usage.get("completion_tokens", 0) - _turn_completion_before
                    reply_text += turn_text
                    logger.info(f"Stream turn {turn + 1} complete | text_len={len(turn_text)} tool_calls={len(tool_calls)}")

                except Exception as stream_err:
                    err_str = str(stream_err)
                    logger.error(f"Streaming error at turn {turn + 1} after all retries: {err_str[:300]}", exc_info=True)
                    if is_fatal_error(stream_err):
                        user_msg = "There was a configuration error with the AI service. Please contact support if this persists."
                    elif is_quota_error(stream_err):
                        user_msg = "The AI service is currently rate-limited. Please wait a moment and try again."
                    elif is_model_incompatible_error(stream_err):
                        user_msg = "None of the available AI models could process this request. Please try rephrasing or simplifying your message."
                    else:
                        user_msg = "I encountered an error while generating a response. Please try again."
                    yield {"event": "error", "message": user_msg}
                    hard_error_occurred = True
                    break

                if turn_text:
                    try:
                        saved_msg = await self.conversation_service.store.save_message(conversation_id=conv.id, role="assistant", content=turn_text, token_count=_turn_completion or None, source=message_source)
                        if saved_msg is not None:
                            saved_assistant_count += 1
                    except Exception as save_err:
                        logger.warning(f"Could not save assistant message (non-fatal): {save_err}")

                if tool_calls:
                    messages.append(Message(role="assistant", tool_calls=[ToolCall(id=tc.id, name=tc.name, args=tc.args) for tc in tool_calls], created_at=datetime.utcnow()))
                elif turn_text:
                    messages.append(Message(role="assistant", content=_format_timestamp(datetime.utcnow()) + turn_text, created_at=datetime.utcnow()))

                is_valid, validation_msg = _validate_contents_ordering(messages)
                if not is_valid:
                    logger.error(f"Messages invalid after appending model response at turn {turn + 1}: {validation_msg}")
                    _log_contents_structure(messages, f"Invalid after turn {turn + 1} model response")
                    yield {"event": "error", "message": "Internal error: Conversation structure became invalid. Please start a new conversation."}
                    hard_error_occurred = True
                    break

                if not tool_calls:
                    logger.info(f"Streaming finished at turn {turn + 1} (no tool calls)")
                    break

                execution_list, should_break, limit_reply = await self.tool_service.check_tool_limits(tool_calls, tool_call_counts, is_streaming=True)

                if should_break:
                    if limit_reply:
                        yield {"event": "token", "text": limit_reply}
                        reply_text += limit_reply
                    break

                tool_result_msgs = []
                current_turn_id = uuid7()

                if settings.AGENT_PARALLEL_TOOL_EXECUTION:
                    for tc, tool_name, tool_args in execution_list:
                        logger.info(f"Streaming parallel tool: {tool_name} | args: {tool_args}")
                        yield {"event": "tool_start", "tool_name": tool_name, "tool_args": tool_args}

                    async def _exec_parallel(tc, name, args):
                        # A fresh session per concurrently-gathered call — AsyncSession
                        # is not safe for concurrent use, and every tool handler here
                        # touches the DB, so sharing the request-scoped `ctx.async_db()`
                        # across `asyncio.gather` causes intermittent
                        # "another operation is in progress" / "Session is already
                        # flushing" failures once two handlers' awaits interleave.
                        async with AsyncSessionLocal() as db:
                            call_ctx = ToolContext(
                                user_id=ctx.user_id, async_db=db,
                                workspace_id=ctx.workspace_id, conversation_id=ctx.conversation_id,
                            )
                            result = await self.tool_service.execute_single_tool(name, args, call_ctx)
                        return tc, name, args, result

                    exec_results = await asyncio.gather(
                        *[_exec_parallel(tc, n, a) for tc, n, a in execution_list]
                    )

                    for tc, tool_name, tool_args, result in exec_results:
                        source_id_counter += 1
                        result["source_id"] = f"S{source_id_counter}"

                        await self._check_proactive_triggers(tool_name=tool_name, tool_result=result, history=[], ctx=ctx)

                        yield {"event": "tool_result", "tool_name": tool_name, "success": bool(result.get("success")), "result": result.get("result"), "error": result.get("error")}

                        if tool_name == "update_note":
                            inner = result.get("result", {})
                            if inner.get("proposal_id"):
                                yield {"event": "note_diff", "proposal_id": inner["proposal_id"], "note_id": inner.get("id"), "base_version": inner.get("version")}

                        if tool_name == "propose_plan":
                            inner = result.get("result", {})
                            if inner.get("proposal_id"):
                                yield {"event": "plan_proposal", "proposal_id": inner["proposal_id"], "item_count": inner.get("item_count")}

                        if tool_name == "ask_user_choice":
                            inner = result.get("result", {})
                            yield {"event": "ask_choice", "questions": inner.get("questions", [])}

                        await self.store.save_message(
                            conversation_id=conv.id, role="tool", tool_name=tool_name,
                            tool_input=tool_args, tool_output=result, tool_call_id=tc.id,
                            turn_id=current_turn_id, source=message_source,
                        )

                        tool_result_msgs.append(Message(
                            role="tool", tool_result=ToolResult(tool_call_id=tc.id, name=tool_name, content=result),
                            created_at=datetime.utcnow(),
                        ))
                else:
                    for tc, tool_name, tool_args in execution_list:
                        logger.info(f"Streaming sequential tool: {tool_name} | args: {tool_args}")
                        yield {"event": "tool_start", "tool_name": tool_name, "tool_args": tool_args}

                        result, tool_msg, source_id_counter = await self.tool_service.execute_single_tool_streaming(
                            tc, tool_name, tool_args, conv, ctx, current_turn_id, source_id_counter,
                            source=message_source,
                        )
                        tool_result_msgs.append(tool_msg)

                        await self._check_proactive_triggers(tool_name=tool_name, tool_result=result, history=[], ctx=ctx)

                        yield {"event": "tool_result", "tool_name": tool_name, "success": bool(result.get("success")), "result": result.get("result"), "error": result.get("error")}

                        if tool_name == "update_note":
                            inner = result.get("result", {})
                            if inner.get("proposal_id"):
                                yield {"event": "note_diff", "proposal_id": inner["proposal_id"], "note_id": inner.get("id"), "base_version": inner.get("version")}

                        if tool_name == "propose_plan":
                            inner = result.get("result", {})
                            if inner.get("proposal_id"):
                                yield {"event": "plan_proposal", "proposal_id": inner["proposal_id"], "item_count": inner.get("item_count")}

                        if tool_name == "ask_user_choice":
                            inner = result.get("result", {})
                            yield {"event": "ask_choice", "questions": inner.get("questions", [])}

                if tool_result_msgs:
                    messages.extend(tool_result_msgs)
                    is_valid, validation_msg = _validate_contents_ordering(messages)
                    if not is_valid:
                        logger.error(f"Messages invalid after appending tool responses at turn {turn + 1}: {validation_msg}")
                        _log_contents_structure(messages, "Invalid after tool responses")
                        yield {"event": "error", "message": "Internal error: Tool response created invalid conversation structure. Please try again."}
                        hard_error_occurred = True
                        break

                turn += 1

            _synth_completion = 0

            if turn >= MAX_TOOL_TURNS and not reply_text and not hard_error_occurred:
                logger.warning(f"event=max_tool_turns_hit turn_count={turn} conversation_id={conv.id} streaming=true")
                try:
                    synthesis_config = GenerationConfig(system_instruction=gen_config.system_instruction, temperature=gen_config.temperature)
                    synthesis_text = ""
                    _synth_completion_before = total_usage.get("completion_tokens", 0)
                    async for chunk in _model_client.stream(messages, synthesis_config, tools=None, preferred_model=preferred_model):
                        if chunk.content:
                            synthesis_text += chunk.content
                            yield {"event": "token", "text": chunk.content}
                        if chunk.usage:
                            for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                                total_usage[k] = total_usage.get(k, 0) + (chunk.usage.get(k) or 0)
                    _synth_completion = total_usage.get("completion_tokens", 0) - _synth_completion_before
                    reply_text = synthesis_text or "I reached my processing limit for this request. Please try a simpler or more specific question."
                except Exception as synth_exc:
                    logger.warning(f"Streaming synthesis turn failed (non-fatal): {synth_exc}")
                    limit_text = "I reached my processing limit for this request. Please try a simpler or more specific question."
                    reply_text = limit_text
                    yield {"event": "token", "text": limit_text}
                    _synth_completion = 0

            if reply_text and saved_assistant_count == 0:
                try:
                    await self.conversation_service.store.save_message(conversation_id=conv.id, role="assistant", content=reply_text, token_count=_synth_completion or None, source=message_source)
                except Exception as save_err:
                    logger.warning(f"Could not save final reply (non-fatal): {save_err}")

            await self.conversation_service.update_timestamp(conv.id)
            await self.conversation_service.increment_message_count(conv.id)

            if total_usage.get("total_tokens"):
                try:
                    await self.conversation_service.increment_token_count(conv.id, total_usage["total_tokens"])
                except Exception as tok_err:
                    logger.warning(f"Could not record token count (non-fatal): {tok_err}")

            await self.memory_service.maybe_trigger(summarizer, conv)
            await self.db.commit()

            if not conversation_id_str:
                conversation_id_str = str(conv.id)
            yield {"event": "done", "conversation_id": conversation_id_str, "usage": total_usage, "model_used": last_model_used or "auto"}
            logger.info(f"event=token_breakdown_total estimated_system_prompt_tokens={total_usage['estimated_system_prompt_tokens']} estimated_history_tokens={total_usage['estimated_history_tokens']} estimated_current_input_tokens={total_usage['estimated_current_input_tokens']} estimated_tool_results_tokens={total_usage['estimated_tool_results_tokens']} prompt_tokens={total_usage['prompt_tokens']} completion_tokens={total_usage['completion_tokens']} total_tokens={total_usage['total_tokens']} conversation_id={conversation_id_str}")
            logger.info(f"Streaming completed | conversation={conversation_id_str} | hard_error={hard_error_occurred} | usage={total_usage}")

        except Exception as exc:
            logger.error(f"Unhandled error in streaming generator: {exc}", exc_info=True)
            try:
                await self.db.rollback()
            except Exception:
                pass
            yield {"event": "error", "message": "An unexpected error occurred while processing your request."}
            if conversation_id_str:
                yield {"event": "done", "conversation_id": conversation_id_str}
            elif conv is not None:
                try:
                    yield {"event": "done", "conversation_id": str(conv.id)}
                except Exception:
                    pass
        finally:
            if ctx is not None:
                try:
                    ctx.close()
                except Exception:
                    pass
