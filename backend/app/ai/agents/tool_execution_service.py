"""ToolExecutionService — manages tool execution loop, limits, proactive triggers."""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.events.event_bus import get_event_bus
from app.events.payloads import ToolExecutedPayload
from app.events.schemas import EventEnvelope
from app.ai.agents.model_client import (
    ModelClient,
    AllModelsExhaustedError,
    is_fatal_error,
    is_quota_error,
    is_model_incompatible_error,
    get_default_model,
)
from app.ai.agents.provider_types import (
    Message,
    GenerationConfig,
    ToolCall,
    ToolResult,
    ProviderResponse,
    ProviderStreamChunk,
)
from app.ai.agents.tool_context import ToolContext
from app.ai.agents.tool_registry import ToolRegistry
from app.ai.agents.conversation_store import ConversationStore
from app.config import settings
from app.utils.logger import get_logger
from app.utils.tokens import estimate_tokens, estimate_message_tokens

logger = get_logger(__name__)

MAX_TOOL_TURNS = 30
MAX_SAME_TOOL_CALLS = 20


def _sum_message_tokens(msgs: list[Message]) -> int:
    total = 0
    for msg in msgs:
        if msg.role == "tool" and msg.tool_result:
            total += estimate_message_tokens(
                role="tool",
                content=None,
                tool_name=msg.tool_result.name,
                tool_output=msg.tool_result.content,
            )
        elif msg.role == "assistant" and msg.tool_calls:
            tc_text = ", ".join(
                f"{tc.name}({json.dumps(tc.args, default=str, ensure_ascii=False)})"
                for tc in msg.tool_calls
            )
            total += estimate_message_tokens(
                role="assistant",
                content=msg.content or tc_text,
            )
        else:
            total += estimate_message_tokens(
                role=msg.role,
                content=msg.content,
            )
    return total


def _estimate_token_breakdown(
    messages: list[Message],
    system_instruction: str,
    turn: int,
) -> dict[str, int]:
    system_prompt_tokens = estimate_tokens(system_instruction) if system_instruction else 0

    if turn == 0:
        if not messages:
            return {
                "estimated_system_prompt_tokens": system_prompt_tokens,
                "estimated_history_tokens": 0,
                "estimated_current_input_tokens": 0,
                "estimated_tool_results_tokens": 0,
            }
        current_input_messages = [messages[-1]]
        history_messages = messages[:-1]
        tool_results_messages = []
    else:
        last_assistant_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "assistant" and messages[i].tool_calls:
                last_assistant_idx = i
                break

        if last_assistant_idx is not None:
            history_messages = messages[:last_assistant_idx]
            current_input_messages = [messages[last_assistant_idx]]
            tool_results_messages = messages[last_assistant_idx + 1:]
        else:
            history_messages = messages
            current_input_messages = []
            tool_results_messages = []

    history_tokens = _sum_message_tokens(history_messages)
    current_input_tokens = _sum_message_tokens(current_input_messages)
    tool_results_tokens = _sum_message_tokens(tool_results_messages)

    return {
        "estimated_system_prompt_tokens": system_prompt_tokens,
        "estimated_history_tokens": history_tokens,
        "estimated_current_input_tokens": current_input_tokens,
        "estimated_tool_results_tokens": tool_results_tokens,
    }


def _query_schedule_conflicts_sync(
    schedule_id: str | None,
    user_id: UUID,
    check_start: datetime,
    check_end: datetime,
) -> str | None:
    from app.database import SessionLocal
    from app.services.schedule_service import ScheduleService

    db = SessionLocal()
    try:
        svc = ScheduleService(db)
        result = svc.list_schedules_for_agent(
            user_id=user_id,
            start_date=check_start,
            end_date=check_end,
        )
        conflicts = []
        for sched in result.get("schedules", []):
            sid = sched.get("id")
            if schedule_id and sid and str(sid) == schedule_id:
                continue
            s_start = sched.get("start_time")
            s_end = sched.get("end_time")
            s_title = sched.get("title", "Untitled")
            if s_start and s_end:
                conflicts.append(f"'{s_title}' ({s_start} — {s_end})")

        if conflicts:
            return f"Bạn có lịch trùng giờ: {'; '.join(conflicts[:3])}."
        return None
    finally:
        db.close()


def _validate_contents_ordering(messages: list[Message]) -> tuple[bool, str]:
    if not messages:
        return True, "Messages array is empty"

    prev_role = None
    pending_tool_call_ids: set[str] = set()

    for i, msg in enumerate(messages):
        curr_role = msg.role

        if curr_role == "tool":
            if prev_role not in ("assistant", "tool"):
                return False, (
                    f"Tool message at index {i} without preceding assistant/tool. "
                    f"tool messages must follow an assistant message with tool_calls."
                )
            if not msg.tool_result:
                return False, f"Tool message at index {i} missing tool_result."
            tcid = msg.tool_result.tool_call_id
            if tcid not in pending_tool_call_ids:
                return False, (
                    f"Tool message at index {i} has tool_call_id={tcid!r} not among "
                    f"pending tool_calls {sorted(pending_tool_call_ids)}."
                )
            pending_tool_call_ids.discard(tcid)
        else:
            if pending_tool_call_ids:
                return False, (
                    f"Message at index {i} (role={curr_role}) appears before pending "
                    f"tool_calls resolved: {sorted(pending_tool_call_ids)}."
                )
            if prev_role is not None and prev_role == curr_role:
                return False, (
                    f"Role violation at index {i}: two consecutive '{curr_role}' roles. "
                    f"Expected alternation: user→model→user→model..."
                )

        if msg.tool_calls:
            if curr_role != "assistant":
                return False, f"tool_calls at index {i} must be in 'assistant' role."
            ids = [tc.id for tc in msg.tool_calls]
            if len(ids) != len(set(ids)):
                return False, f"Duplicate tool_call ids at index {i}: {ids}"
            pending_tool_call_ids = set(ids)

        if msg.tool_result and curr_role != "tool":
            return False, f"tool_result at index {i} must be in 'tool' role."

        prev_role = curr_role

    if pending_tool_call_ids:
        last_msg = messages[-1] if messages else None
        if not (
            last_msg is not None
            and last_msg.role == "assistant"
            and last_msg.tool_calls
            and pending_tool_call_ids == {tc.id for tc in last_msg.tool_calls}
        ):
            return False, f"Unresolved tool_calls at end: {sorted(pending_tool_call_ids)}."

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


class ToolExecutionService:
    """Manages tool execution: loop control, limits, parallel/sequential execution, proactive triggers."""

    def __init__(self, user, db: AsyncSession, store: ConversationStore, registry: ToolRegistry):
        self.user = user
        self.db = db
        self.store = store
        self.registry = registry
        self._event_bus = None  # Lazy init

    async def _get_event_bus(self):
        if self._event_bus is None:
            self._event_bus = await get_event_bus()
        return self._event_bus

    async def _publish_tool_executed(
        self,
        tool_name: str,
        ctx: ToolContext,
        *,
        success: bool,
        duration_ms: int,
        action_id: str | None = None,
        error: str | None = None,
    ) -> None:
        try:
            bus = await self._get_event_bus()
            await bus.publish(EventEnvelope(
                type="tool.executed",
                source="ToolExecutionService",
                user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
                payload=ToolExecutedPayload(
                    tool_name=tool_name,
                    conversation_id=ctx.conversation_id,
                    success=success,
                    duration_ms=duration_ms,
                    action_id=action_id,
                    error=error,
                ).model_dump(),
            ))
        except Exception as exc:
            logger.warning(f"Failed to publish tool.executed event: {exc}")

    async def execute_tools_pass(
        self,
        tool_calls: list,
        conv,
        ctx: ToolContext,
        turn: int,
        tool_call_counts: dict[str, int],
        source_id_counter: int,
        workspace_id: UUID | None,
    ):
        """
        Execute all tool_calls for one turn.
        Returns (tool_result_messages, should_break, reply_text, source_id_counter).
        Note: limit checking is done by caller (check_tool_limits).
        """
        should_break = False
        reply_text = None
        tool_result_messages: list[Message] = []
        current_turn_id = uuid.uuid4()

        execution_list = []
        for tc in tool_calls:
            tool_name = tc.name
            if not tool_name:
                logger.warning(f"Skipping tool call with empty name (id={tc.id})")
                continue
            tool_args = tc.args
            execution_list.append((tc, tool_name, tool_args))

        exec_results: list[tuple] = []
        if not should_break and execution_list:

            if settings.AGENT_PARALLEL_TOOL_EXECUTION:
                async def _exec_parallel(tc, name, args):
                    logger.info(f"Parallel executing tool: {name} with args: {args}")
                    start_time = time.time()
                    try:
                        result = await self.registry.execute(name, args, ctx)
                        logger.info(f"Tool '{name}' executed | result: {str(result)[:200]}")
                    except Exception as tool_exc:
                        logger.error(f"Tool '{name}' raised exception: {tool_exc}", exc_info=True)
                        result = {"error": str(tool_exc), "success": False}
                    duration_ms = int((time.time() - start_time) * 1000)
                    await self._publish_tool_executed(
                        name, ctx,
                        success=result.get("success", True),
                        duration_ms=duration_ms,
                        action_id=result.get("action_id"),
                        error=result.get("error"),
                    )
                    return tc, name, result

                exec_results = await asyncio.gather(
                    *[_exec_parallel(tc, n, a) for tc, n, a in execution_list]
                )
            else:
                for tc, tool_name, tool_args in execution_list:
                    logger.info(f"Sequential executing tool: {tool_name} with args: {tool_args}")
                    start_time = time.time()
                    try:
                        result = await self.registry.execute(tool_name, tool_args, ctx)
                        logger.info(f"Tool '{tool_name}' executed | result: {str(result)[:200]}")
                    except Exception as tool_exc:
                        logger.error(f"Tool '{tool_name}' raised exception: {tool_exc}", exc_info=True)
                        result = {"error": str(tool_exc), "success": False}
                    duration_ms = int((time.time() - start_time) * 1000)
                    await self._publish_tool_executed(
                        tool_name, ctx,
                        success=result.get("success", True),
                        duration_ms=duration_ms,
                        action_id=result.get("action_id"),
                        error=result.get("error"),
                    )
                    exec_results.append((tc, tool_name, result))

            for tc, tool_name, result in exec_results:
                source_id_counter += 1
                result["source_id"] = f"S{source_id_counter}"

                await self.store.save_message(
                    conversation_id=conv.id,
                    role="tool",
                    tool_name=tool_name,
                    tool_input=tc.args,
                    tool_output=result,
                    tool_call_id=tc.id,
                    turn_id=current_turn_id,
                )

                tool_result_messages.append(
                    Message(
                        role="tool",
                        tool_result=ToolResult(
                            tool_call_id=tc.id,
                            name=tool_name,
                            content=result,
                        ),
                        created_at=datetime.utcnow(),
                    )
                )

        return tool_result_messages, exec_results, should_break, reply_text, source_id_counter

    async def check_tool_limits(
        self,
        tool_calls: list,
        tool_call_counts: dict[str, int],
        is_streaming: bool = False,
    ):
        """
        Check tool limits and build execution list.
        Returns (execution_list, should_break, reply_text).
        """
        should_break = False
        reply_text = None
        execution_list = []

        for tc in tool_calls:
            tool_name = tc.name
            if not tool_name:
                logger.warning(f"Skipping tool call with empty name (id={tc.id})")
                continue
            tool_args = tc.args

            tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
            if tool_call_counts[tool_name] > MAX_SAME_TOOL_CALLS:
                logger.warning(
                    f"event=max_same_tool_calls_hit "
                    f"tool_name={tool_name} "
                    f"count={tool_call_counts[tool_name]}"
                )
                if is_streaming:
                    reply_text = (
                        "\n\nI wasn't able to find what you were looking for. "
                        "Could you provide more details?"
                    )
                else:
                    reply_text = (
                        "I wasn't able to find the information you requested. "
                        "Could you provide more details?"
                    )
                should_break = True
                break

            execution_list.append((tc, tool_name, tool_args))

        return execution_list, should_break, reply_text

    async def execute_single_tool(self, tool_name: str, tool_args: dict, ctx: ToolContext) -> dict:
        start_time = time.time()
        try:
            logger.info(f"Executing tool: {tool_name} with args: {tool_args}")
            result = await self.registry.execute(tool_name, tool_args, ctx)
            logger.info(f"Tool '{tool_name}' executed | result: {str(result)[:200]}")
        except Exception as tool_exc:
            logger.error(f"Tool '{tool_name}' raised exception: {tool_exc}", exc_info=True)
            result = {"error": str(tool_exc), "success": False}

        duration_ms = int((time.time() - start_time) * 1000)
        await self._publish_tool_executed(
            tool_name, ctx,
            success=result.get("success", True),
            duration_ms=duration_ms,
            action_id=result.get("action_id"),
            error=result.get("error"),
        )
        return result

    async def execute_single_tool_streaming(
        self,
        tc,
        tool_name: str,
        tool_args: dict,
        conv,
        ctx: ToolContext,
        current_turn_id,
        source_id_counter: int,
    ):
        """Execute one tool for streaming mode. Returns (result, tool_message, source_id_counter)."""
        result = await self.execute_single_tool(tool_name, tool_args, ctx)
        source_id_counter += 1
        result["source_id"] = f"S{source_id_counter}"

        await self.store.save_message(
            conversation_id=conv.id,
            role="tool",
            tool_name=tool_name,
            tool_input=tool_args,
            tool_output=result,
            tool_call_id=tc.id,
            turn_id=current_turn_id,
        )

        tool_message = Message(
            role="tool",
            tool_result=ToolResult(tool_call_id=tc.id, name=tool_name, content=result),
            created_at=datetime.utcnow(),
        )

        return result, tool_message, source_id_counter

    def log_token_breakdown(self, bd: dict, turn: int, conv_id: UUID) -> None:
        logger.info(
            f"event=token_breakdown "
            f"turn={turn + 1} "
            f"estimated_system_prompt_tokens={bd['estimated_system_prompt_tokens']} "
            f"estimated_history_tokens={bd['estimated_history_tokens']} "
            f"estimated_current_input_tokens={bd['estimated_current_input_tokens']} "
            f"estimated_tool_results_tokens={bd['estimated_tool_results_tokens']} "
            f"conversation_id={conv_id}"
        )

    # ------------------------------------------------------------------
    # Proactive triggers
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
        schedule_id = tool_result.get("id")
        start_str = tool_result.get("start_time")
        end_str = tool_result.get("end_time")
        title = tool_result.get("title", "Untitled")

        if not start_str or not end_str:
            logger.debug("No start_time/end_time in tool_result — skipping conflict check")
            return

        try:
            new_start = datetime.fromisoformat(start_str)
            new_end = datetime.fromisoformat(end_str)
        except (ValueError, TypeError) as exc:
            logger.debug(f"Cannot parse schedule times: {exc}")
            return

        check_start = new_start - timedelta(minutes=15)
        check_end = new_end + timedelta(minutes=15)

        conflict_warning = await asyncio.to_thread(
            _query_schedule_conflicts_sync,
            schedule_id=str(schedule_id) if schedule_id else None,
            user_id=ctx.user_id,
            check_start=check_start,
            check_end=check_end,
        )

        if conflict_warning:
            tool_result["conflict_warning"] = conflict_warning
            logger.info(f"Schedule conflict detected for '{title}': {conflict_warning}")

    async def _check_note_action_suggestions(
        self, tool_result: dict, history: list, ctx: ToolContext
    ) -> None:
        tool_result["suggestion"] = {
            "type": "tip",
            "message": (
                "Bạn có thể tổ chức note bằng màu sắc (xanh, đỏ, tím, hồng) "
                "hoặc sắp xếp vào notebook để dễ tìm lại sau."
            ),
        }

    async def _check_knowledge_suggestions(
        self, tool_result: dict, history: list, ctx: ToolContext
    ) -> None:
        logger.debug("Knowledge search not yet implemented — no suggestions")
