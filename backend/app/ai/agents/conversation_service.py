"""ConversationService — manages conversation lifecycle, history loading, and system prompt construction."""

import json
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.ai.agents.conversation_store import ConversationStore
from app.ai.agents.conversation_summarizer import ConversationSummarizer, get_conversation_summarizer
from app.ai.agents.model_client import ModelClient
from app.ai.agents.provider_types import Message, GenerationConfig, ToolCall, ToolResult
from app.ai.skills import get_skill_retriever, get_skill_registry
from app.config import settings
from app.utils.logger import get_logger
from app.utils.tokens import estimate_tokens, estimate_message_tokens

logger = get_logger(__name__)

MAX_CONVERSATION_HISTORY = 10
MAX_TOKENS_PER_DAY_PER_USER = 2_000_000
MAX_HISTORY_TOKENS = 8000


def _format_timestamp(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return f"[{dt.strftime('%Y-%m-%d %H:%M:%S UTC')}] "


def _get_message_created_at(record) -> datetime | None:
    try:
        return getattr(record, "created_at", None)
    except Exception:
        return None


def _inject_context_into_text(text: str, ctx: dict | None) -> str:
    if not ctx:
        return text
    parts = []
    pills = ctx.get('pills', [])
    page = ctx.get('page', None)
    runtime = ctx.get('runtime', None)
    if pills:
        pills_text = '\n\n---\n\n'.join(p['text'] for p in pills if p.get('text'))
        parts.append(f"Context:\n\n{pills_text}")
    if page:
        if isinstance(page, dict):
            page_lines = [f"{k}: {v}" for k, v in page.items() if v]
            parts.append("Page Context:\n\n" + '\n'.join(page_lines))
        else:
            parts.append(f"Page Context:\n\n{page}")
    if runtime:
        if isinstance(runtime, dict):
            runtime_lines = [f"{k}: {v}" for k, v in runtime.items() if v]
            parts.append(f"Runtime UI Context:\n\n" + '\n'.join(runtime_lines))
        else:
            parts.append(f"Runtime UI Context:\n\n{runtime}")
    if parts:
        return '\n\n'.join(parts) + f"\n\n{text}"
    return text


def _message_full_text(msg) -> str:
    content = getattr(msg, 'content', '') or ''
    ctx = getattr(msg, 'context', None)
    ts = _get_message_created_at(msg)
    enriched = _inject_context_into_text(content, ctx)
    return _format_timestamp(ts) + enriched


def _trim_incomplete_tail(messages: list[Message], label: str) -> None:
    def _message_has_tool_calls(msg: Message) -> bool:
        return bool(msg.tool_calls)

    removed = 0
    while messages and messages[-1].role in ("user", "tool"):
        messages.pop()
        removed += 1
        if messages and messages[-1].role == "assistant" and _message_has_tool_calls(messages[-1]):
            messages.pop()
            removed += 1
    if removed:
        logger.info(f"Trimmed {removed} trailing history item(s) before appending current user ({label})")


def _build_history_contents(records: list) -> list[Message]:
    records = list(records)
    # "system" is exempt from the leading trim below — it never enters the
    # user/assistant alternation state machine (see the `role == "system"`
    # branch), so it must not be discarded alongside genuinely orphaned
    # assistant/tool records at the front of history.
    while records and records[0].role not in ("user", "system"):
        records.pop(0)
    if not records:
        return []

    messages: list[Message] = []
    expected_role = "user"
    i = 0
    n = len(records)
    # Notifications the Attention Gate delivered via Mezon, buffered until
    # the next real turn so the AI sees them without them counting as a
    # turn of their own (R5, docs/mezon-bot-plan.md §V). If nothing follows
    # in this batch, they're dropped for *this* call only — the row is
    # still in the DB and will attach to the next real message once one
    # arrives in a later call.
    pending_system_notes: list[str] = []

    while i < n:
        record = records[i]
        role = getattr(record, "role", None)
        ts = _get_message_created_at(record)

        if role == "system":
            note_text = _message_full_text(record)
            if note_text:
                pending_system_notes.append(note_text)
            i += 1

        elif role == "user":
            user_text = _message_full_text(record)
            if not user_text:
                i += 1
                continue
            if expected_role != "user":
                logger.info(f"Skipping out-of-order user message (expected {expected_role})")
                i += 1
                continue
            if pending_system_notes:
                user_text = "[Hệ thống đã nhắc] " + "\n[Hệ thống đã nhắc] ".join(pending_system_notes) + "\n" + user_text
                pending_system_notes = []
            messages.append(Message(role="user", content=user_text, created_at=ts))
            expected_role = "assistant"
            i += 1

        elif role == "assistant":
            raw_content = getattr(record, "content", None)
            if expected_role != "assistant":
                logger.info(f"Skipping out-of-order assistant message (expected {expected_role})")
                i += 1
                continue
            if not raw_content:
                logger.info(f"Skipping empty assistant message (content is {raw_content!r})")
                i += 1
                continue
            assistant_text = _format_timestamp(ts) + raw_content
            if pending_system_notes:
                assistant_text = "[Hệ thống đã nhắc] " + "\n[Hệ thống đã nhắc] ".join(pending_system_notes) + "\n" + assistant_text
                pending_system_notes = []
            messages.append(Message(role="assistant", content=assistant_text, created_at=ts))
            expected_role = "user"
            i += 1

        elif role == "tool":
            if expected_role != "assistant":
                logger.info(f"Skipping out-of-order tool message (expected {expected_role})")
                i += 1
                continue

            turn_id = getattr(record, "turn_id", None)
            group = []
            j = i
            while j < n and getattr(records[j], "role", None) == "tool":
                rec_turn_id = getattr(records[j], "turn_id", None)
                if turn_id is not None and rec_turn_id != turn_id:
                    break
                if turn_id is None and rec_turn_id is not None:
                    break
                group.append(records[j])
                j += 1

            tool_calls = []
            tool_results = []
            for idx, rec in enumerate(group):
                tool_name = getattr(rec, "tool_name", None)
                tool_input = getattr(rec, "tool_input", None)
                tool_output = getattr(rec, "tool_output", None)
                if not (tool_name and tool_input is not None and tool_output is not None):
                    logger.info(f"Skipping incomplete tool record in group: tool_name={tool_name}")
                    continue
                tcid = getattr(rec, "tool_call_id", None) or f"{tool_name}_{idx}"
                tool_calls.append(ToolCall(id=tcid, name=tool_name, args=tool_input or {}))
                tool_results.append(
                    ToolResult(tool_call_id=tcid, name=tool_name, content=tool_output or {})
                )

            if tool_calls:
                messages.append(Message(role="assistant", tool_calls=tool_calls, created_at=ts))
                for tr in tool_results:
                    messages.append(Message(role="tool", tool_result=tr, created_at=ts))
                expected_role = "assistant"

            i = j
        else:
            logger.info(f"Skipping unknown role message: {role}")
            i += 1

    return messages


class ConversationService:
    """Manages conversation lifecycle: get/create, history loading, system prompt building."""

    def __init__(self, user: User, db: AsyncSession, store: ConversationStore | None = None):
        self.user = user
        self.db = db
        self.store = store or ConversationStore(db)

    async def get_or_create(
        self,
        conversation_id: UUID | None,
        project_id: UUID | None,
        message: str,
    ) -> tuple:
        """Get existing conversation or create new one (generates title for new)."""
        generated_title = None
        if conversation_id:
            conv = await self.store.get_conversation_by_id(conversation_id, self.user.id)
            if not conv:
                logger.warning(
                    f"Conversation not found for user {self.user.id}: {conversation_id}"
                )
                return None, "Conversation not found. Please start a new chat."
        else:
            # Hội thoại thuộc về một người, không thuộc container nào —
            # xem `ConversationStore.get_or_create_conversation`.
            conv = await self.store.get_or_create_conversation(user_id=self.user.id)
            try:
                new_title = await self._generate_conversation_title(message)
                await self.store.update_conversation_title(conv.id, new_title)
                conv.title = new_title
                generated_title = new_title
                logger.info(f"Generated title for conversation {conv.id}: {new_title}")
            except Exception as exc:
                logger.warning(f"Title generation failed (non-fatal): {exc}")

        return conv, generated_title

    async def check_token_budget(self, conv) -> tuple[bool, str | None]:
        """Check if user has exceeded daily token budget."""
        if conv.total_token_count and conv.total_token_count >= MAX_TOKENS_PER_DAY_PER_USER:
            logger.warning(
                f"User {self.user.id} exceeded daily token budget | "
                f"used={conv.total_token_count}/{MAX_TOKENS_PER_DAY_PER_USER}"
            )
            return False, "You have reached your daily AI interaction limit. Please try again tomorrow."
        return True, None

    async def get_summarizer(self) -> ConversationSummarizer | None:
        try:
            return get_conversation_summarizer(self.db)
        except Exception as exc:
            logger.warning(f"Error creating summarizer (non-fatal): {exc}")
            return None

    async def build_system_prompt(
        self,
        conv,
        message: str,
        context: dict | None,
        summarizer: ConversationSummarizer | None,
        system_prompt: str,
        context_string: str | None = None,
        recent_messages: list | None = None,
    ) -> str:
        """Build system prompt with summary context, skill section, and
        (Milestone 1.7) ContextService's project/recent-activity section.

        `context_string` comes from `UnifiedContext.to_llm_string()`
        (app/context/) — it's the NEW, DB-sourced part (project/recent
        notes/upcoming schedules). It's separate from `context` (the
        frontend's raw pills/page/runtime dict), which still goes through
        `_inject_context_into_text` per-message as before — not duplicated
        here.
        """
        if summarizer and conv.summary:
            try:
                summary_context = await summarizer.get_conversation_context(
                    conv.id, include_summary=True
                )
                if summary_context:
                    system_prompt = f"{system_prompt}\n\n{summary_context}"
            except Exception as exc:
                logger.warning(f"Error getting summary context: {exc}")

        if context_string:
            system_prompt = f"{system_prompt}\n\n{context_string}"

        skill_section = self._build_skill_section(message, context, recent_messages)
        if skill_section:
            system_prompt = f"{system_prompt}\n\n{skill_section}"

        return system_prompt

    async def load_history(self, conv_id: UUID, last_summary_id: UUID | None = None) -> list:
        """Load messages since the last summary cursor.

        When last_summary_id is available, only loads messages after that cursor
        (un-summarized region). The summary injected in the system prompt covers
        everything before the cursor, so loading from the end would waste budget
        on already-summarized content.

        Falls back to the old token-budget or message-count strategy when
        no cursor exists (pre-first-extraction conversations).
        """
        if last_summary_id is not None:
            recent_messages = await self.store.get_messages_since(conv_id, last_summary_id)
            logger.info(
                f"Loaded {len(recent_messages)} messages since cursor "
                f"(conversation {conv_id}, cursor={str(last_summary_id)[:8]}…)"
            )
            return recent_messages

        if settings.AGENT_TOKEN_BUDGET_HISTORY:
            recent_messages = await self.store.get_recent_messages_by_token_budget(
                conv_id, max_tokens=MAX_HISTORY_TOKENS,
            )
        else:
            recent_messages = await self.store.get_recent_messages(
                conv_id, limit=MAX_CONVERSATION_HISTORY
            )
        logger.info(f"Loaded {len(recent_messages)} historical messages (no cursor, conversation {conv_id})")
        return recent_messages

    async def save_user_message(self, conv_id: UUID, message: str, context: dict | None, source: str | None = None) -> None:
        await self.store.save_message(
            conversation_id=conv_id,
            role="user",
            content=message,
            context=context,
            source=source,
        )

    async def increment_message_count(self, conv_id: UUID) -> None:
        await self.store.increment_message_count(conv_id)

    async def update_timestamp(self, conv_id: UUID) -> None:
        await self.store.update_conversation_timestamp(conv_id)

    async def increment_token_count(self, conv_id: UUID, token_count: int) -> None:
        await self.store.increment_token_count(conv_id, token_count)

    def build_messages_from_history(self, recent_messages: list, message: str, context: dict | None) -> list[Message]:
        messages = _build_history_contents(recent_messages)
        _trim_incomplete_tail(messages, "messages")
        current_text = _inject_context_into_text(message, context)
        now = datetime.utcnow()
        messages.append(Message(role="user", content=_format_timestamp(now) + current_text, created_at=now))
        return messages

    def log_raw_messages(self, recent_messages: list, label: str = "Messages") -> None:
        if not recent_messages:
            return
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
        logger.info(f"Raw DB messages ({label}):\n  " + "\n  ".join(msg_summary))

    # ------------------------------------------------------------------
    # Title generation
    # ------------------------------------------------------------------

    async def _generate_conversation_title(self, message: str) -> str:
        try:
            prompt = f"""Generate a very short conversation title (max 10 words) based on this message:

"{message}"

Return ONLY the title, no quotes or explanation."""

            msgs = [
                Message(role="user", content=prompt, created_at=datetime.utcnow()),
            ]

            gen_config = GenerationConfig(
                system_instruction="You are a helpful assistant that creates concise, descriptive conversation titles.",
                temperature=0.7,
            )

            logger.info(f"Generating title for new conversation...")
            title_client = ModelClient()
            model_used, response = await title_client.generate(msgs, gen_config)

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
    # Skill injection
    # ------------------------------------------------------------------

    def _extract_recent_user_texts(self, recent_messages: list | None, limit: int = 2) -> str:
        """Last `limit` user-turn texts from history, oldest-first.

        Short follow-up replies ("6 tháng", "09:00") carry no keywords of
        their own — without the preceding user turns, skill retrieval goes
        blank right when the ASK->PLAN handoff needs it most.
        """
        if not recent_messages:
            return ""
        texts: list[str] = []
        for msg in reversed(recent_messages):
            if getattr(msg, "role", None) == "user" and getattr(msg, "content", None):
                texts.append(msg.content)
                if len(texts) >= limit:
                    break
        texts.reverse()
        return " ".join(texts)

    def _build_skill_section(self, message: str, context: dict | None = None, recent_messages: list | None = None) -> str:
        try:
            retriever = get_skill_retriever()
            registry = get_skill_registry()

            history_text = self._extract_recent_user_texts(recent_messages)
            retrieval_text = f"{history_text} {message}".strip() if history_text else message

            selected = retriever.select(retrieval_text, context, max_skills=4)
            if not selected:
                return ""

            resolved_names = registry.resolve_dependencies([s.name for s in selected])
            skills = registry.load_all(resolved_names)
            blocks: list[str] = []
            for skill in skills:
                blocks.append(
                    f"=== SKILL: {skill.metadata.name.upper()} ===\n{skill.prompt}"
                )
            section = "\n\n".join(blocks)
            logger.info(
                "Injected skills: primary=%s resolved=%s (%d total chars)",
                [s.name for s in selected],
                resolved_names,
                len(section),
            )
            return section
        except Exception as exc:
            logger.warning(f"Skill injection failed (non-fatal): {exc}")
            return ""
