"use strict";

/**
 * Turning an inbound message into an action.
 *
 * The split is: anything starting with the prefix goes to a command;
 * everything else is conversation with the AI, streamed from
 * `/api/agent/stream/chat` and rendered by editing one Mezon message in
 * place (M3 — R2 + R3, see `_handleConversation` and `StreamThrottle`).
 */

const { logger } = require("./logger");
const { text } = require("./mezon/embed");
const { splitMezonContent } = require("./mezon/markdown");
const { StreamThrottle } = require("./mezon/streamThrottle");
const { ThinkingTimeline } = require("./mezon/thinking");
const { parseButtonEvent, getText, getDate } = require("./mezon/interactions");
const { parseActionId } = require("./mezon/actions");
const { PendingForms } = require("./mezon/pendingForms");
const { renderAskChoice, readAnswers, renderAnsweredCard } = require("./mezon/askChoice");
const { renderModelSaved, MODEL_FIELD_ID } = require("./mezon/modelCard");
const {
  renderTaskCompleted,
  renderTaskCreated,
  TASK_FIELD_ID,
  TITLE_FIELD_ID,
  DUE_FIELD_ID,
  PRIORITY_FIELD_ID,
} = require("./mezon/taskCards");
const { renderMuted, renderInboxCleared, REASON_FIELD_ID } = require("./mezon/inboxCards");
const {
  renderPlanProposal,
  renderPlanApproved,
  renderPlanRejected,
  renderPlanAlreadyDecided,
} = require("./mezon/planCard");

// Message scopes this bot answers in. See `MezonGateway._normalise` for
// how a scope is derived, and why `mode` is the only field that can
// decide it.
const SERVED_SCOPES = new Set(["dm"]);

// Idle timeout for an agent stream, deliberately decoupled from
// `CORTEX_TIMEOUT_MS` (which stays short — a few seconds — for every
// other call this bot makes, like `resolveChannel`). A real agent turn
// can go quiet for a while mid-stream with no bug involved: a slow model
// provider, several chained tool calls, or the backend's own
// retry-with-fallback logic between models, none of which emit an SSE
// frame while they're working. 30s was cutting off answers that were
// still genuinely in progress. This is not "no timeout" — an actually
// wedged connection must still let go eventually — just long enough that
// it is not the thing users hit in normal use.
const AGENT_STREAM_IDLE_TIMEOUT_MS = 15 * 60 * 1000;

class MessageRouter {
  constructor({ gateway, registry, cortex, storage, prefix, keepThinking = true }) {
    this.gateway = gateway;
    this.registry = registry;
    this.cortex = cortex;
    this.storage = storage;
    this.prefix = prefix;
    // See `config.bot.keepThinking` — leave the thinking block under the
    // finished answer instead of clearing it. Default-on here too, so a
    // router built without the flag behaves like a deployed one.
    this.keepThinking = keepThinking;

    // Questions waiting to be answered, keyed by the id on their submit
    // button — see `mezon/pendingForms.js` for why this is in memory.
    this.pendingForms = new PendingForms();

    // Plan decisions currently mid-flight, so a double-click cannot get
    // two approvals past the status check at once. The check itself is
    // in `_handlePlanDecision`; this only closes the window between
    // reading the status and acting on it.
    this._planDecisionsInFlight = new Set();
  }

  /**
   * Who is this, in Cortex terms?
   *
   * A failure to reach the backend is reported as `{ linked: false,
   * error: true }` rather than throwing, so an outage degrades to "I can't
   * check right now" instead of silence. Silence is the one response that
   * looks identical to the bot being dead.
   */
  async _identify(mezonUserId) {
    try {
      const result = await this.cortex.resolveChannel(mezonUserId);
      return { linked: Boolean(result?.linked), userId: result?.user_id ?? null };
    } catch (err) {
      logger.warn("identity lookup failed", { error: err?.message });
      return { linked: false, error: true };
    }
  }

  async handleMessage(message) {
    // M1 serves one-to-one DMs and nothing else, stated as a list rather
    // than as `if (!isDirectMessage) return` so the decision is visible
    // and cheap to widen later.
    //
    // Why not clan channels or groups: a bot that answers every message in
    // a shared space is a bot that gets muted. Serving those well means
    // answering only when mentioned, and deciding whose Cortex account a
    // message in a shared room acts on — a design question of its own, not
    // a default to drift into.
    if (!SERVED_SCOPES.has(message.scope)) {
      logger.debug("ignoring message outside served scope", {
        scope: message.scope,
        mode: message.mode,
        channel_id: message.channelId,
      });
      return;
    }

    const reply = async (content, attachments) => {
      const payload = typeof content === "string" ? text(content) : content;
      return this.gateway.sendToChannel(message.channelId, payload, attachments);
    };

    const identity = await this._identify(message.senderId);

    if (identity.error) {
      await reply("⚠️ Không kết nối được tới Cortex. Thử lại sau ít phút.");
      return;
    }

    const parsed = this.registry.parse(message.text);
    if (parsed) {
      await this.registry.dispatch(parsed, {
        message,
        identity,
        cortex: this.cortex,
        storage: this.storage,
        registry: this.registry,
        prefix: this.prefix,
        // `*model` renders a form whose submission comes back as a button
        // click, so it needs the same store the agent's `ask_choice`
        // cards use — see `mezon/pendingForms.js`.
        pendingForms: this.pendingForms,
        reply,
      });
      return;
    }

    await this._handleConversation({ message, identity, reply });
  }

  /**
   * Keeps as many messages as needed in sync with the growing buffer —
   * `splitMezonContent` (mezon/markdown.js) is what decides a chunk
   * boundary is needed at all (Mezon's own ~4000-char cap on `content`);
   * this is just the bookkeeping for turning "N chunks" into "N Mezon
   * messages", most turns being the ordinary case of exactly one.
   * `messageIds` is mutated in place — the caller owns it across the
   * whole stream, since a later `push()` may need to create another
   * message on top of ones already sent for this same turn.
   *
   * `state.settledCount` tracks how many *leading* chunks already carry
   * their final content and must never be touched again — not simply
   * "already sent": a chunk that is still the *last* one is still
   * growing, so "message exists at this index" alone isn't enough to
   * skip it (that bug shipped once: it skipped editing the very first
   * chunk's real content because a message already existed there — the
   * placeholder — even though the placeholder had never been replaced
   * yet). A chunk only ever settles the moment a *later* chunk appears
   * after it, at which point it gets one last edit with its now-final
   * content and is never revisited — re-sending an already-settled
   * chunk on every following tick would multiply `editMessage` calls for
   * no visible change, defeating the whole point of `StreamThrottle`'s
   * coalescing.
   */
  async _syncMultiMessage(channelId, messageIds, body, state) {
    const chunks = splitMezonContent(body);
    for (let i = 0; i < chunks.length; i++) {
      if (i < state.settledCount) continue;
      const isLast = i === chunks.length - 1;

      const content = chunks[i];
      if (i < messageIds.length) {
        await this.gateway.editMessage(channelId, messageIds[i], content);
      } else {
        const sent = await this.gateway.sendToChannel(channelId, content);
        if (!sent?.id) {
          // Same dead end as the placeholder's own send failing below:
          // nothing to address a further edit to. `messageIds` is left
          // as it was, so the next tick retries this same overflow
          // chunk rather than silently losing it.
          logger.warn("overflow message send returned no id; stopping further sync for this turn");
          return;
        }
        messageIds.push(sent.id);
      }
      if (!isLast) state.settledCount = i + 1;
    }
  }

  /**
   * DM → AI, streamed by editing messages in place (M3 — R2 + R3).
   *
   * The placeholder is sent *before* the agent call starts, not after the
   * first token — the wait for a first token is where a reply feels
   * slowest, and a static "⏳ đang nghĩ…" answers that immediately. Every
   * following update rewrites a message via `StreamThrottle`, which owns
   * the "when is an edit actually worth sending" decision (see its own
   * docstring for why that throttling is mandatory). A long enough body
   * grows past one message — `_syncMultiMessage` is what turns that into
   * more Mezon messages instead of `mezon-sdk` throwing.
   *
   * **Two surfaces, two messages.** The thinking transcript and the
   * answer are streamed independently, and that is not a layout
   * preference:
   *
   * - It is what lets the transcript be *complete*. Sharing one message
   *   meant the block was concatenated with the answer before
   *   `splitMezonContent` cut it, so every character of reasoning was a
   *   character the answer could not have — which is why it used to be
   *   capped hard enough to read as a summary of the thinking rather
   *   than the thinking. Web parity was impossible in one message.
   * - It puts the thoughts *above* the answer, as on the web. The
   *   placeholder becomes whichever surface speaks first: thinking
   *   claims it when reasoning arrives before any answer token (the
   *   normal case, since models reason first), and the answer then opens
   *   its own message below. When there is no reasoning at all, the
   *   placeholder simply stays the answer and nothing changes from M3.
   *
   * The alternative — one message, bigger caps — was rejected for a
   * third reason too: `_syncMultiMessage` seals a chunk once a later one
   * exists, so a block that grows and then disappears at the end of the
   * turn can leave a sealed message showing text that is no longer part
   * of anything. Separate messages make each stream append-only, which is
   * the property that machinery actually needs.
   */
  async _handleConversation({ message, identity, reply }) {
    if (!identity.linked) {
      await reply(
        "Chào bạn 👋 Tài khoản Mezon này chưa liên kết với Cortex.\n" +
          `Mở Cortex trên web → Settings → Liên kết Mezon để lấy mã, rồi gõ \`${this.prefix}link <mã>\`.`
      );
      return;
    }

    const channelId = message.channelId;
    const placeholder = await reply("⏳ đang nghĩ…");
    if (!placeholder?.id) {
      // No id back from the send — can't edit what we can't address. Log
      // and fall through to the placeholder as the final answer rather
      // than throwing, since the user at least got *a* reply.
      logger.warn("placeholder send returned no message id; cannot stream-edit");
      return;
    }

    // Mutated in place, never reassigned: both arrays are captured by the
    // throttles' edit closures, and `_syncMultiMessage` appends to them
    // as a body outgrows one message.
    const answerIds = [placeholder.id];
    const thinkingIds = [];
    const answerState = { settledCount: 0 };
    const thinkingState = { settledCount: 0 };

    const throttle = new StreamThrottle({
      edit: (body) => this._syncMultiMessage(channelId, answerIds, body, answerState),
    });
    const thinkingThrottle = new StreamThrottle({
      edit: (body) => this._syncMultiMessage(channelId, thinkingIds, body, thinkingState),
    });
    const timeline = new ThinkingTimeline();

    // Hand the placeholder to the transcript, but only while the answer
    // has not started: message order in a channel is send order, so this
    // is the only moment at which thoughts can end up above the answer.
    // Once a token has arrived the placeholder is the answer, and a
    // transcript opening later simply goes below it — chronological, and
    // still true.
    const claimPlaceholderForThinking = () => {
      if (thinkingIds.length || throttle.buffer || !answerIds.length) return;
      thinkingIds.push(...answerIds.splice(0, answerIds.length));
    };

    const showThinking = ({ immediate }) => {
      claimPlaceholderForThinking();
      thinkingThrottle.replace(timeline.render(), { immediate });
    };

    // Interactive cards the turn asked for. Collected during the stream
    // and sent *after* it, as separate messages, for two reasons: the
    // streamed message is being rewritten by `StreamThrottle` on every
    // edit, so an embed placed on it would be overwritten within the
    // second; and the web renders these below the answer text too
    // (`MessageList.tsx`), so a card that appeared before the sentence
    // introducing it would read wrong on both surfaces.
    const cards = { choices: [], plans: [] };

    /**
     * The turn is over, whichever way it went.
     *
     * `keepThinking` decides between the two endings. Deleting is what
     * the web does — its timeline is unmounted the moment `msg.loading`
     * clears, and an edit cannot express "this was never worth a
     * message". Keeping it is the debugging view, and then the block is
     * re-rendered in its finished form ("Đã suy nghĩ") rather than left
     * frozen mid-sentence claiming work is still in progress.
     */
    const endTimeline = async () => {
      if (timeline.isEmpty() || !thinkingIds.length) return;

      if (this.keepThinking) {
        thinkingThrottle.replace(timeline.render({ done: true }), { immediate: false });
        await thinkingThrottle.flush();
        return;
      }

      await thinkingThrottle.flush();
      for (const id of thinkingIds.splice(0, thinkingIds.length)) {
        try {
          await this.gateway.deleteMessage(channelId, id);
        } catch (err) {
          // A transcript that will not delete is not worth failing a
          // turn over — the answer is the deliverable.
          logger.warn("could not delete thinking message", { error: err?.message });
        }
      }
    };

    try {
      await this.cortex.streamChat({
        userId: identity.userId,
        message: message.text,
        timeoutMs: AGENT_STREAM_IDLE_TIMEOUT_MS,
        onEvent: (event) => {
          if (event.event === "token" && event.text) {
            throttle.push(event.text);
          } else if (event.event === "reasoning_token" && event.text) {
            timeline.reasoning(event.text);
            // Throttled: these arrive as fast as answer tokens do.
            showThinking({ immediate: false });
          } else if (event.event === "tool_start") {
            timeline.toolStart(event.tool_name, event.tool_args);
            showThinking({ immediate: true });
          } else if (event.event === "tool_result") {
            timeline.toolResult(event.tool_name, {
              result: event.result,
              success: event.success,
              error: event.error,
            });
            showThinking({ immediate: true });
          } else if (event.event === "ask_choice" && Array.isArray(event.questions) && event.questions.length) {
            cards.choices.push(event.questions);
          } else if (event.event === "plan_proposal" && event.proposal_id) {
            cards.plans.push(event.proposal_id);
          } else if (event.event === "error") {
            logger.warn("agent stream reported an error event", { message: event.message });
          }
        },
      });
      // Thinking first: it settles the message above before the answer
      // below it finishes, which is the order they are read in.
      await endTimeline();
      await throttle.flush();
      // Nothing anywhere — no answer, and no transcript to stand in for
      // one. The placeholder is still sitting there saying the bot is
      // thinking, so it has to say something else.
      if (!throttle.buffer && timeline.isEmpty()) {
        await this.gateway.editMessage(channelId, placeholder.id, text("…"));
      }
    } catch (err) {
      logger.warn("agent stream failed", { error: err?.message });
      // A long-but-progressing answer (several tool calls, a longer
      // generation) can still fail partway — an idle timeout, the
      // connection dropping. Whatever already streamed to the user is a
      // real partial answer, not garbage; replacing it outright with a
      // generic "sự cố" message would throw away the one thing they can
      // already see working, so the note is appended instead — unless
      // nothing ever arrived, in which case there is nothing to append to.
      //
      // Routed back through the throttle (not a direct `editMessage`) so
      // its own `flush()` cancels whatever edit timer was still pending
      // from the last `push()` — bypassing it here would leave that timer
      // alive to fire later and silently overwrite this very message with
      // a stale, note-less edit.
      await endTimeline();
      throttle.push(
        throttle.buffer
          ? "\n\n⚠️ (bị ngắt giữa chừng, có thể chưa đầy đủ)"
          : "⚠️ AI đang gặp sự cố, thử lại sau ít phút."
      );
      await throttle.flush();
    }

    // Sent on the error path too, not just the happy one. A
    // `plan_proposal` is a row already written to the database — the
    // stream dying afterwards makes the answer incomplete, not the
    // proposal imaginary, and swallowing the card would leave the user
    // with a plan they can only reach by opening the web app.
    await this._sendTurnCards({ channelId, identity, cards, reply });
  }

  /**
   * The interactive cards a turn produced: a plan to approve, questions
   * to answer.
   *
   * Each card is sent inside its own try/catch because the answer has
   * already been delivered by this point. A card failing should cost the
   * user that card, not turn a finished reply into an error.
   */
  async _sendTurnCards({ channelId, identity, cards, reply }) {
    for (const proposalId of cards.plans) {
      try {
        const proposal = await this.cortex.getPlanProposal(proposalId, identity.userId);
        await this.gateway.sendToChannel(channelId, renderPlanProposal(proposal, { proposalId }));
      } catch (err) {
        logger.warn("could not render plan proposal card", { proposalId, error: err?.message });
        // Named as a real thing the user can go and act on, rather than
        // hidden: the proposal exists whether or not the preview loaded.
        await reply(
          "📋 Cortex đã đề xuất một kế hoạch nhưng bot không tải được bản xem trước. " +
            "Mở Cortex trên web để xem và duyệt."
        );
      }
    }

    for (const questions of cards.choices) {
      try {
        const formId = this.pendingForms.put({ questions });
        await this.gateway.sendToChannel(channelId, renderAskChoice(questions, formId));
      } catch (err) {
        logger.warn("could not render ask_choice card", { error: err?.message });
        // The questions themselves are not lost — they are in the answer
        // text above, and prose answers work exactly as well.
        await reply("❓ (Không dựng được form chọn — bạn cứ trả lời bằng tin nhắn thường nhé.)");
      }
    }
  }

  /**
   * Button clicks — the half of M4 that makes the bot two-way.
   *
   * Selecting an option in a dropdown fires this same event with the
   * select's own id and a bare, non-JSON `extra_data` — so an
   * unrecognised `button_id` is normal traffic to be ignored, not an
   * error to report (§VIII bis 8b). `parseActionId` returning null *is*
   * that filter; see `mezon/actions.js`.
   *
   * The actor is `user_id`, never `sender_id` — the latter is whoever
   * authored the message carrying the button, which for our own cards is
   * always the bot. `parseButtonEvent` already names it `actorId` so no
   * call site has to remember that.
   */
  async handleButton(event) {
    const parsed = parseButtonEvent(event);
    const action = parseActionId(parsed.buttonId);
    if (!action) {
      logger.debug("button event not addressed to us", { buttonId: parsed.buttonId });
      return;
    }
    if (!parsed.channelId) {
      logger.warn("button event without a channel id; nowhere to reply", { buttonId: parsed.buttonId });
      return;
    }

    const reply = async (content, attachments) => {
      const payload = typeof content === "string" ? text(content) : content;
      return this.gateway.sendToChannel(parsed.channelId, payload, attachments);
    };

    // Same identity rules as a message: a button press acts on a Cortex
    // account, so it needs the same verified link a chat turn does. The
    // card being visible is not authorisation — it says only that this
    // channel was sent one.
    const identity = await this._identify(parsed.actorId);
    if (identity.error) {
      await reply("⚠️ Không kết nối được tới Cortex. Thử lại sau ít phút.");
      return;
    }
    if (!identity.linked) {
      await reply(`Tài khoản Mezon này chưa liên kết với Cortex — gõ \`${this.prefix}link <mã>\` trước đã.`);
      return;
    }

    try {
      if (action.kind === "plan_approve" || action.kind === "plan_reject") {
        await this._handlePlanDecision({ action, parsed, identity, reply });
      } else if (action.kind === "ask_submit") {
        await this._handleChoiceSubmit({ action, parsed, identity, reply });
      } else if (action.kind === "model_submit") {
        await this._handleModelSubmit({ action, parsed, identity, reply });
      } else if (action.kind === "task_complete") {
        await this._handleTaskComplete({ action, parsed, identity, reply });
      } else if (action.kind === "task_create") {
        await this._handleTaskCreate({ action, parsed, identity, reply });
      } else if (action.kind === "mute_submit") {
        await this._handleMuteSubmit({ action, parsed, identity, reply });
      } else if (action.kind === "inbox_read_all") {
        await this._handleInboxReadAll({ action, parsed, identity, reply });
      }
    } catch (err) {
      logger.warn("button action failed", { kind: action.kind, error: err?.message });
      await reply(`⚠️ Không thực hiện được: ${err?.message ?? "lỗi không rõ"}`);
    }
  }

  /**
   * Replace a card with what it became.
   *
   * Editing rather than replying is what takes the buttons away — the new
   * content carries no `components`, so the decision cannot be made
   * twice from the same message. Falls back to a new message if the edit
   * fails, because the user must learn the outcome either way; the
   * duplicate-click risk that reopens is covered by the status check in
   * `_handlePlanDecision`.
   */
  async _replaceCard(parsed, content, reply) {
    if (parsed.messageId) {
      try {
        await this.gateway.editMessage(parsed.channelId, parsed.messageId, content);
        return;
      } catch (err) {
        logger.warn("could not edit card in place; sending the outcome as a new message", {
          error: err?.message,
        });
      }
    }
    await reply(content);
  }

  /**
   * ✅ Tạo tất cả / ✋ Bỏ qua on a plan proposal.
   *
   * The status is read before acting, and that round trip is not
   * defensive padding. The backend refuses to approve a `rejected` or an
   * `expired` proposal but **allows approving an already-approved one**,
   * which would create every task and event a second time. On the web
   * the card disappears once decided; here a message with live buttons
   * outlives the process that sent it, so a click after a restart —
   * or on scrollback a week later — is exactly the shape of that bug.
   * The in-flight set closes the remaining window between reading the
   * status and changing it.
   */
  async _handlePlanDecision({ action, parsed, identity, reply }) {
    const proposalId = action.targetId;
    if (this._planDecisionsInFlight.has(proposalId)) {
      logger.debug("plan decision already in flight; ignoring the repeat click", { proposalId });
      return;
    }
    this._planDecisionsInFlight.add(proposalId);
    try {
      const proposal = await this.cortex.getPlanProposal(proposalId, identity.userId);
      if (proposal?.status && proposal.status !== "pending") {
        await this._replaceCard(parsed, renderPlanAlreadyDecided(proposal.status), reply);
        return;
      }

      if (action.kind === "plan_approve") {
        const result = await this.cortex.approvePlanProposal(proposalId, identity.userId);
        await this._replaceCard(parsed, renderPlanApproved(result), reply);
        logger.info("plan proposal approved from Mezon", {
          proposalId,
          created: result?.created_count,
          failed: result?.failed_count,
        });
        return;
      }

      await this.cortex.rejectPlanProposal(proposalId, identity.userId);
      await this._replaceCard(parsed, renderPlanRejected(), reply);
      logger.info("plan proposal rejected from Mezon", { proposalId });
    } finally {
      this._planDecisionsInFlight.delete(proposalId);
    }
  }

  /**
   * A form whose backing data the bot no longer has.
   *
   * Every card built from a fetched list needs the list again on submit —
   * to name what was picked, not to decide anything — so they all share
   * this one reply rather than each inventing its own wording.
   */
  async _expiredForm(reply, command) {
    await reply(`Form này đã hết hạn. Gõ lại \`${this.prefix}${command}\` nhé.`);
  }

  /** Đánh dấu xong on the `*tasks` card. */
  async _handleTaskComplete({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    if (!pending) return this._expiredForm(reply, "tasks");

    const taskId = getText(parsed.extra.values, TASK_FIELD_ID);
    if (!taskId) {
      await reply("Chưa chọn việc nào — chọn một việc rồi bấm lại.");
      return;
    }

    // The transition itself is the backend's: `TASK_STATUS_TRANSITIONS`
    // rejects anything illegal, so a stale card cannot complete a task
    // twice by being clicked twice — the second call fails and says so.
    await this.cortex.completeTask(taskId, identity.userId);
    this.pendingForms.delete(action.targetId);

    const task = pending.tasks.find((t) => String(t.id) === taskId) ?? { title: taskId };
    await this._replaceCard(parsed, renderTaskCompleted(task), reply);
    logger.info("task completed from Mezon", { taskId, actor: parsed.actorId });
  }

  /**
   * Tạo on the `*new` form.
   *
   * The date picker yields `YYYY-MM-DD` and `TaskCreate.due_date` is a
   * datetime, so a time has to be invented. Midnight UTC is the honest
   * choice: `today.py` compares `.date()` on both sides — overdue and
   * due-today are day-granular there by design — so the time component
   * never reaches a decision, and picking one that *looks* meaningful
   * (23:59, or a local end-of-day) would imply a precision the ranking
   * does not use. `getDate` is what rejects the five-digit years the
   * platform itself lets through (§VIII bis 8a).
   */
  async _handleTaskCreate({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    if (!pending) return this._expiredForm(reply, "new");

    const title = (getText(parsed.extra.values, TITLE_FIELD_ID, "") ?? "").trim();
    if (!title) {
      await reply("Việc cần có tiêu đề — điền vào rồi bấm Tạo.");
      return;
    }

    const due = getDate(parsed.extra.values, DUE_FIELD_ID);
    const priority = getText(parsed.extra.values, PRIORITY_FIELD_ID);

    const created = await this.cortex.createTask(
      {
        title,
        ...(due ? { due_date: `${due}T00:00:00Z` } : {}),
        ...(priority ? { priority } : {}),
      },
      identity.userId
    );
    this.pendingForms.delete(action.targetId);

    await this._replaceCard(parsed, renderTaskCreated(created ?? { title }), reply);
    logger.info("task created from Mezon", { title, actor: parsed.actorId });
  }

  /** Tắt on the `*mute` picker. */
  async _handleMuteSubmit({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    if (!pending) return this._expiredForm(reply, "mute");

    const reasonKey = getText(parsed.extra.values, REASON_FIELD_ID);
    if (!reasonKey) {
      await reply("Chưa chọn loại nhắc nào.");
      return;
    }

    await this.cortex.setReasonEnabled(reasonKey, false, identity.userId);
    this.pendingForms.delete(action.targetId);

    const reason = pending.reasons.find((r) => r.reason_key === reasonKey) ?? { reason_key: reasonKey };
    await this._replaceCard(parsed, renderMuted(reason), reply);
    logger.info("reason muted from Mezon", { reasonKey, actor: parsed.actorId });
  }

  /** Đánh dấu đã đọc hết on the `*inbox` card. */
  async _handleInboxReadAll({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    await this.cortex.markAllNotificationsRead(identity.userId);
    this.pendingForms.delete(action.targetId);
    await this._replaceCard(parsed, renderInboxCleared(pending?.notificationCount ?? 0), reply);
  }

  /**
   * Lưu on the `*model` picker.
   *
   * The backend is what validates the id — it rejects anything outside
   * the catalogue rather than storing it (see `update_chat_model`), which
   * is the only place the difference between "a model you can pick" and
   * "a string that will be silently ignored at request time" is visible.
   * So this sends the submitted value as-is and lets a 400 surface
   * through `handleButton`'s catch.
   */
  async _handleModelSubmit({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    if (!pending) {
      await reply(`Form này đã hết hạn. Gõ lại \`${this.prefix}model\` để chọn.`);
      return;
    }

    const chosenId = getText(parsed.extra.values, MODEL_FIELD_ID);
    if (!chosenId) {
      await reply("Chưa chọn model nào — chọn một cái rồi bấm Lưu.");
      return;
    }

    const model = pending.models.find((m) => m.id === chosenId) ?? { id: chosenId, label: chosenId };
    await this.cortex.setChatModel(chosenId, identity.userId);
    this.pendingForms.delete(action.targetId);

    await this._replaceCard(parsed, renderModelSaved(model), reply);
    logger.info("chat model changed from Mezon", { model: chosenId, actor: parsed.actorId });
  }

  /**
   * Gửi on an `ask_choice` form.
   *
   * There is no endpoint to call: `ask_user_choice.py` is a pure UI
   * handoff, and the answer's only destination is the conversation
   * itself, as the user's next message. So this ends by running a normal
   * chat turn with the summary text — the same string the web sends, so
   * a conversation that moved between surfaces reads the same to the
   * model.
   *
   * An untouched field is absent from the payload rather than empty
   * (§VIII bis 8b), which makes "answered nothing" and "answered with a
   * blank" indistinguishable here. The web gates its submit button on
   * every question being answered; a Mezon button cannot be gated, so
   * the same check happens after the click and says which question is
   * still open.
   */
  async _handleChoiceSubmit({ action, parsed, identity, reply }) {
    const pending = this.pendingForms.get(action.targetId);
    if (!pending) {
      await reply(
        "Form này đã hết hạn (thường là do bot vừa khởi động lại). " +
          "Bạn cứ trả lời thẳng bằng tin nhắn thường nhé."
      );
      return;
    }

    const { answers, summaryText, missing } = readAnswers(pending.questions, parsed.extra.values);
    if (missing.length) {
      await reply(
        `Còn thiếu câu ${missing.join(", ")} — chọn đáp án hoặc gõ vào ô “Ý khác” rồi bấm Gửi lại.`
      );
      return;
    }

    this.pendingForms.delete(action.targetId);
    await this._replaceCard(parsed, renderAnsweredCard(pending.questions, answers), reply);

    // A real chat turn, not a shortcut: the answer has to reach the model
    // through the same path a typed message does, or it lands outside the
    // conversation history the next turn is built from.
    await this._handleConversation({
      message: {
        text: summaryText,
        senderId: parsed.actorId,
        channelId: parsed.channelId,
        scope: "dm",
        mode: 4,
      },
      identity,
      reply,
    });
  }
}

module.exports = { MessageRouter };
