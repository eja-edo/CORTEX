"use strict";

/**
 * HTTP client for the Cortex backend.
 *
 * The bot holds no business logic — it asks Cortex, which owns permission
 * checks, the action snapshot store that makes `revert_action` work, and
 * the Attention Gate. Anything the bot decided for itself would be a
 * decision made outside all three.
 *
 * Two auth shapes, and the difference is not cosmetic:
 *
 * - `asUser(userId)` sends `X-User-ID` alongside the internal key, and the
 *   backend then acts as that person. Only valid once the Mezon id has
 *   been resolved to a Cortex user through a verified `user_channels` row.
 * - `asService()` sends the key alone, for endpoints that derive the
 *   subject from their own payload. Redemption is the example: it works
 *   out *which* account to link from the one-time code, so letting the
 *   caller name a user would defeat the code entirely.
 */

const { config } = require("./config");
const { logger } = require("./logger");

class CortexError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "CortexError";
    this.status = status;
    this.body = body;
  }

  /** 4xx that is not 408/429: the same request will fail the same way, so
   *  callers should surface it rather than retry. */
  get isClientError() {
    return this.status >= 400 && this.status < 500 && ![408, 429].includes(this.status);
  }
}

/** `?occurrence_start_time=…&edit_scope=…`, or "" when the write is on an
 *  ordinary task. Both parameters go together or not at all — the API
 *  rejects half of the pair, which is the right shape: "this occurrence"
 *  without saying which, and "which" without saying whether it applies to
 *  the rest, are both incomplete answers. */
function occurrenceQuery(occurrence) {
  if (!occurrence?.startTime || !occurrence?.scope) return "";
  const query = new URLSearchParams({
    occurrence_start_time: occurrence.startTime,
    edit_scope: occurrence.scope,
  });
  return `?${query}`;
}

class CortexClient {
  constructor({ baseUrl, internalApiKey, timeoutMs } = {}) {
    this.baseUrl = baseUrl ?? config.cortex.baseUrl;
    this.internalApiKey = internalApiKey ?? config.cortex.internalApiKey;
    this.timeoutMs = timeoutMs ?? config.cortex.timeoutMs;
  }

  _headers(userId) {
    const headers = {
      "Content-Type": "application/json",
      "X-Internal-API-Key": this.internalApiKey,
    };
    if (userId) headers["X-User-ID"] = String(userId);
    return headers;
  }

  async _request(method, path, { body, userId, timeoutMs } = {}) {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs ?? this.timeoutMs);

    try {
      const response = await fetch(url, {
        method,
        headers: this._headers(userId),
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });

      const raw = await response.text();
      let parsed = null;
      if (raw) {
        try {
          parsed = JSON.parse(raw);
        } catch {
          parsed = raw;
        }
      }

      if (!response.ok) {
        const detail =
          (parsed && typeof parsed === "object" && parsed.detail) || raw || response.statusText;
        throw new CortexError(String(detail), response.status, parsed);
      }
      return parsed;
    } catch (err) {
      if (err instanceof CortexError) throw err;
      if (err?.name === "AbortError") {
        throw new CortexError(`Cortex timeout sau ${timeoutMs ?? this.timeoutMs}ms`, 408, null);
      }
      // Backend down or unreachable. 503 so callers treat it as transient
      // — which it usually is, during a deploy.
      throw new CortexError(`Không gọi được Cortex: ${err?.message}`, 503, null);
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Service-scoped ──────────────────────────────────────────────────────

  /** Exchange a link code for a verified channel. Sends no user id — the
   *  code is what decides whose account this is. */
  redeemLinkCode({ code, address, label }) {
    return this._request("POST", "/api/preferences/channels/redeem", {
      body: { code, channel: "mezon", address, label },
    });
  }

  /**
   * Which Cortex user owns this Mezon account, if any.
   *
   * Service-scoped by necessity: this is the call that establishes which
   * user the bot may then act as, so sending a user id with it would be
   * circular. Only verified links resolve.
   */
  resolveChannel(address) {
    const query = new URLSearchParams({ channel: "mezon", address: String(address) });
    return this._request("GET", `/api/preferences/channels/resolve?${query}`);
  }

  // ── User-scoped ─────────────────────────────────────────────────────────

  listChannels(userId) {
    return this._request("GET", "/api/preferences/channels", { userId });
  }

  /**
   * Stream a chat turn from `/api/agent/stream/chat`, calling `onEvent`
   * with each parsed SSE frame as it arrives (F2/M3, R2).
   *
   * Not built on `_request` — that reads the whole body with
   * `response.text()` before returning, which for a streaming reply means
   * waiting for `done` before the caller sees a single token. `onEvent` is
   * how the caller finds out about tokens as they happen; this method
   * itself resolves once the stream ends (on `done`, `error`, or the
   * connection closing).
   *
   * `surface: "mezon"` is what tells the backend to reuse this user's one
   * long-running Mezon conversation instead of starting a new one every
   * message — see `AgentService.handle_streaming_generator`'s `surface`
   * parameter. No `conversation_id` is ever sent from here; the backend
   * owns finding or creating it.
   *
   * `timeoutMs` is an *idle* timeout, reset on every chunk received, not a
   * deadline for the whole stream. A single fixed deadline was the first
   * version of this and it was wrong: an agent turn with a few tool calls
   * can legitimately run past 30s while still actively streaming, and a
   * flat timeout aborted those mid-answer. Silence, not duration, is what
   * actually indicates something is wrong.
   *
   * `model: "auto"` sent explicitly rather than left out: both resolve to
   * the backend's default model (`ModelClient._resolve` treats an absent,
   * `"auto"`, or unrecognised id the same way), but saying it makes the
   * bot's position explicit rather than accidental — it has no UI to pick
   * a model and wants whatever the default is.
   *
   * This used to describe a round-robin across every enabled model. The
   * backend no longer rotates: one turn runs on one model, so a Mezon
   * conversation is answered by the same model throughout instead of
   * changing voice between turns.
   */
  async streamChat({ userId, message, onEvent, timeoutMs }) {
    const idleTimeout = timeoutMs ?? this.timeoutMs ?? 30000;
    const url = `${this.baseUrl}/api/agent/stream/chat`;
    const controller = new AbortController();
    let timer = setTimeout(() => controller.abort(), idleTimeout);
    const resetIdleTimer = () => {
      clearTimeout(timer);
      timer = setTimeout(() => controller.abort(), idleTimeout);
    };

    let response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: this._headers(userId),
        body: JSON.stringify({ message, surface: "mezon", model: "auto" }),
        signal: controller.signal,
      });
    } catch (err) {
      clearTimeout(timer);
      if (err?.name === "AbortError") {
        throw new CortexError(`Cortex timeout sau ${idleTimeout}ms không có phản hồi`, 408, null);
      }
      throw new CortexError(`Không gọi được Cortex: ${err?.message}`, 503, null);
    }

    if (!response.ok) {
      clearTimeout(timer);
      const raw = await response.text().catch(() => "");
      throw new CortexError(raw || response.statusText, response.status, null);
    }
    if (!response.body) {
      clearTimeout(timer);
      throw new CortexError("Cortex trả về stream rỗng", 502, null);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        resetIdleTimer();
        buffer += decoder.decode(value, { stream: true });

        // SSE frames are blank-line-separated; each frame may carry
        // several "data: ..." lines, though this endpoint only ever
        // emits one per frame.
        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const jsonText = line.slice(5).trim();
            if (!jsonText) continue;
            try {
              onEvent(JSON.parse(jsonText));
            } catch (parseErr) {
              logger.warn("could not parse stream frame", {
                error: parseErr?.message,
                frame: jsonText.slice(0, 200),
              });
            }
          }
        }
      }
    } catch (err) {
      if (err?.name === "AbortError") {
        throw new CortexError(`Cortex im lặng quá ${idleTimeout}ms giữa chừng stream`, 408, null);
      }
      throw new CortexError(`Stream bị ngắt: ${err?.message}`, 503, null);
    } finally {
      clearTimeout(timer);
    }
  }

  // ── Feature endpoints the commands sit on ───────────────────────────
  //
  // Every one of these is a call the web app already makes. The bot picks
  // the endpoint and renders the answer; it never computes one — ranking,
  // risk, "why this task" sentences and permission checks all stay where
  // they are, which is the whole point of the thin-bot rule.

  /** The "Hôm nay" screen: what to do now, and what it costs to skip. */
  getToday(userId) {
    return this._request("GET", "/api/today", { userId });
  }

  /** "What should I do next?" — the same ranking plus the at-risk list. */
  getNextAction(userId) {
    return this._request("GET", "/api/planning/next-action", { userId });
  }

  /** `params` maps straight to the endpoint's query string (`status`,
   *  `due_before`, …) — see `get_tasks` in app/api/tasks.py. */
  listTasks(userId, params = {}) {
    const query = new URLSearchParams(
      Object.entries(params).filter(([, v]) => v !== undefined && v !== null)
    );
    const suffix = query.toString() ? `?${query}` : "";
    return this._request("GET", `/api/tasks${suffix}`, { userId });
  }

  getTask(taskId, userId) {
    return this._request("GET", `/api/tasks/${encodeURIComponent(taskId)}`, { userId });
  }

  /**
   * `occurrence` is `{ startTime, scope }` or null.
   *
   * Required — not optional — when the task is a checklist item on a
   * recurring event: `PATCH /tasks/{id}` and `.../complete` answer 422
   * without it rather than guessing which session was meant (see
   * `TaskService.is_linked_to_recurring_event`). Deciding *which* it is
   * belongs to `taskActions.js`; this only carries the answer.
   */
  completeTask(taskId, userId, occurrence = null) {
    return this._request(
      "POST",
      `/api/tasks/${encodeURIComponent(taskId)}/complete${occurrenceQuery(occurrence)}`,
      { userId }
    );
  }

  updateTask(taskId, body, userId, occurrence = null) {
    return this._request(
      "PATCH",
      `/api/tasks/${encodeURIComponent(taskId)}${occurrenceQuery(occurrence)}`,
      { body, userId }
    );
  }

  createTask(body, userId) {
    return this._request("POST", "/api/tasks", { body, userId });
  }

  getSchedule(scheduleId, userId) {
    return this._request("GET", `/api/schedules/${encodeURIComponent(scheduleId)}`, { userId });
  }

  /** `{ instances, total }` for one recurring event inside a window. The
   *  endpoint refuses (400) for a non-recurring schedule, so callers check
   *  `is_recurring` first rather than using the error as a test. */
  listScheduleInstances(scheduleId, userId, { rangeStart, rangeEnd }) {
    const query = new URLSearchParams({ range_start: rangeStart, range_end: rangeEnd });
    return this._request(
      "GET",
      `/api/schedules/${encodeURIComponent(scheduleId)}/instances?${query}`,
      { userId }
    );
  }

  /** Every registered reason_key with its level and on/off state — the
   *  list `*mute` picks from, fetched rather than hard-coded for the same
   *  reason the model list is. */
  listReasonPreferences(userId) {
    return this._request("GET", "/api/preferences/reasons", { userId });
  }

  setReasonEnabled(reasonKey, enabled, userId) {
    return this._request("PUT", `/api/preferences/reasons/${encodeURIComponent(reasonKey)}`, {
      body: { enabled },
      userId,
    });
  }

  /** `{ items, total }`. The endpoint has no unread filter — every row
   *  carries `read_at`, so which ones are new is decided at render time
   *  rather than by a query parameter that doesn't exist. */
  listNotifications(userId, { limit = 10 } = {}) {
    const query = new URLSearchParams({ limit: String(limit) });
    return this._request("GET", `/api/notifications?${query}`, { userId });
  }

  markAllNotificationsRead(userId) {
    return this._request("POST", "/api/notifications/read-all", { userId });
  }

  /**
   * The models this user may switch between.
   *
   * Fetched, never hard-coded. A list baked into the bot is a list that
   * goes stale the first time the catalogue moves — the exact mistake the
   * plan calls out from 4.2 (Trigger Catalog), where a hard-coded
   * frontend list had to be torn out and replaced with a fetched one.
   */
  listModels(userId) {
    return this._request("GET", "/api/agent/models", { userId });
  }

  getPreferences(userId) {
    return this._request("GET", "/api/preferences", { userId });
  }

  /** Record which model this user's turns run on. `null` clears the
   *  choice, which keeps following the default if the default changes. */
  setChatModel(modelId, userId) {
    return this._request("PUT", "/api/preferences/chat-model", {
      body: { chat_model: modelId ?? null },
      userId,
    });
  }

  /**
   * The items behind a `plan_proposal` stream event.
   *
   * The event carries only an id and a count — deliberately, since a
   * proposal is a DB row that outlives the stream announcing it. So a
   * preview is always this fetch, and approving one long after the
   * conversation moved on still works.
   */
  getPlanProposal(proposalId, userId) {
    return this._request("GET", `/api/plan-proposals/${encodeURIComponent(proposalId)}`, { userId });
  }

  /**
   * Turn the proposal into real tasks and events.
   *
   * No `items` in the body means "create exactly what was proposed" —
   * the endpoint's own default. This surface has no per-item editing (a
   * Mezon form cannot express "drop item 3 and change item 5's date"
   * without becoming a worse version of the web's list), so it is always
   * all or nothing, and "nothing" is the reject button.
   *
   * A longer timeout than the default: approval creates every item
   * one at a time through the same command path the AI uses, so a
   * fifteen-item plan is fifteen writes, not one.
   */
  approvePlanProposal(proposalId, userId) {
    return this._request("POST", `/api/plan-proposals/${encodeURIComponent(proposalId)}/approve`, {
      body: {},
      userId,
      timeoutMs: Math.max(this.timeoutMs, 60000),
    });
  }

  rejectPlanProposal(proposalId, userId) {
    return this._request("POST", `/api/plan-proposals/${encodeURIComponent(proposalId)}/reject`, { userId });
  }

  async health() {
    try {
      await this._request("GET", "/health", { timeoutMs: 5000 });
      return true;
    } catch (err) {
      logger.warn("Cortex health check failed", { error: err?.message });
      return false;
    }
  }
}

module.exports = { CortexClient, CortexError };
