"use strict";

/**
 * HTTP + SSE client for `orchestrator_service` — the (external, not part of
 * this monorepo) service that runs meeting rooms and their LLM summaries,
 * documented in `docs/API_REFERENCE.md`.
 *
 * Mirrors `cortex.js`'s shape on purpose: a thin seam around `fetch`, one
 * error class, nothing decided here that the caller (`roomWatch.js`) should
 * decide instead. The one thing this file owns that `cortex.js` doesn't is
 * its own login — orchestrator issues its own JWTs, separate from anything
 * Cortex hands out, via `POST /auth/mezon/bot/login` with the same Mezon
 * bot credentials this process already holds (`config.mezon`) rather than a
 * second set of secrets to provision and rotate.
 */

const { config } = require("./config");
const { logger } = require("./logger");

class OrchestratorError extends Error {
  constructor(message, status, body) {
    super(message);
    this.name = "OrchestratorError";
    this.status = status;
    this.body = body;
  }
}

// Backoff schedule for the metadata SSE stream. Capped rather than
// exponential-forever: a five-minute-old backoff on a link that recovered
// seconds ago would leave the bot deaf to `room_ended`/`room_summary_done`
// for no reason once orchestrator is back.
const RECONNECT_DELAYS_MS = [1000, 2000, 5000, 10000, 30000];

class OrchestratorClient {
  constructor({ baseUrl, botId, botToken, timeoutMs } = {}) {
    this.baseUrl = baseUrl ?? config.orchestrator.baseUrl;
    this.botId = botId ?? config.mezon.botId;
    this.botToken = botToken ?? config.mezon.token;
    this.timeoutMs = timeoutMs ?? config.orchestrator.timeoutMs;
    this._accessToken = null;
    this._loginPromise = null;
    this._stopped = false;
    this._controller = null;
  }

  async _login() {
    const response = await fetch(`${this.baseUrl}/auth/mezon/bot/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account: { appid: this.botId, token: this.botToken } }),
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
      const detail = (parsed && typeof parsed === "object" && parsed.detail) || raw || response.statusText;
      throw new OrchestratorError(`Đăng nhập orchestrator thất bại: ${detail}`, response.status, parsed);
    }
    const accessToken = parsed?.access_token;
    if (!accessToken) {
      throw new OrchestratorError("Orchestrator bot login không trả về access_token", 502, parsed);
    }
    logger.info("orchestrator bot login ok");
    this._accessToken = accessToken;
    return accessToken;
  }

  /** Only ever one login in flight, even if several requests race in at
   *  startup before the first one lands. */
  async _ensureToken() {
    if (this._accessToken) return this._accessToken;
    if (!this._loginPromise) {
      this._loginPromise = this._login().finally(() => {
        this._loginPromise = null;
      });
    }
    return this._loginPromise;
  }

  /**
   * One retry on 401 with a fresh login, then give up — a second 401 right
   * after re-authenticating is a real permission problem (see the plan's
   * note on `rooms:view_all`), not a stale token.
   */
  async _request(method, path, { body, retryOn401 = true } = {}) {
    const token = await this._ensureToken();
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);

    let response;
    try {
      response = await fetch(url, {
        method,
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (err) {
      if (err?.name === "AbortError") {
        throw new OrchestratorError(`Orchestrator timeout sau ${this.timeoutMs}ms`, 408, null);
      }
      throw new OrchestratorError(`Không gọi được orchestrator: ${err?.message}`, 503, null);
    } finally {
      clearTimeout(timer);
    }

    if (response.status === 401 && retryOn401) {
      this._accessToken = null;
      return this._request(method, path, { body, retryOn401: false });
    }

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
      const detail = (parsed && typeof parsed === "object" && parsed.detail) || raw || response.statusText;
      throw new OrchestratorError(String(detail), response.status, parsed);
    }
    return parsed;
  }

  /**
   * The room's participants, among other fields — needed at `room_ended`
   * time because the SSE push for that event carries no participant list
   * (API doc §10). Returns `null` if the room id is unknown.
   */
  async getRoomById(roomId) {
    const result = await this._request("GET", `/rooms/id/${encodeURIComponent(roomId)}`);
    return result?.room ?? null;
  }

  /** `.data` of `GET /summary/room/id/{room_id}` — one summary object
   *  (`{ summary_data: { summary, action_items, detail }, ... }`), or
   *  `null` if the room has no summary row at all yet. */
  async getSummaryByRoomId(roomId) {
    const result = await this._request("GET", `/summary/room/id/${encodeURIComponent(roomId)}`);
    return result?.data ?? null;
  }

  /**
   * Connect to `GET /sse/metadata` and call `onEvent(parsedEvent)` for
   * every frame, reconnecting with backoff for as long as `stop()` hasn't
   * been called. Built the same way `cortex.js#streamChat` reads
   * `data:`-framed SSE off a `fetch` body reader — Node has no built-in
   * `EventSource`, and this is one more dependency than the file's own
   * docstring says this codebase wants.
   *
   * Fire-and-forget by design: it runs for the lifetime of the process (or
   * until `stop()`), and a dropped connection is something this method
   * recovers from itself rather than something the caller retries.
   */
  streamMetadata({ onEvent }) {
    this._stopped = false;
    (async () => {
      let attempt = 0;
      while (!this._stopped) {
        try {
          await this._connectMetadataOnce(onEvent);
          attempt = 0; // a connection that ran a while before dropping isn't a repeat failure
        } catch (err) {
          // A deliberate `stop()` aborts the in-flight fetch, which surfaces
          // here as this same catch — not a real drop, so it doesn't
          // deserve the same warning a genuine disconnect does.
          if (!this._stopped) {
            logger.warn("orchestrator metadata stream dropped", { error: err?.message });
          }
        }
        if (this._stopped) break;
        const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
        attempt++;
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    })();
  }

  /** Aborts the live SSE connection, if any, so shutdown actually closes
   *  the socket instead of leaving it open until the process exits. */
  stop() {
    this._stopped = true;
    this._controller?.abort();
  }

  async _connectMetadataOnce(onEvent) {
    const token = await this._ensureToken();
    const controller = new AbortController();
    this._controller = controller;
    let response;
    try {
      response = await fetch(`${this.baseUrl}/sse/metadata`, {
        headers: { Authorization: `Bearer ${token}`, Accept: "text/event-stream" },
        signal: controller.signal,
      });
    } catch (err) {
      throw new OrchestratorError(`Không kết nối được SSE orchestrator: ${err?.message}`, 503, null);
    }

    if (response.status === 401) {
      // Same token-expiry story as `_request`, but the stream has no
      // built-in retry loop of its own — `streamMetadata`'s outer loop is
      // what reconnects, so clearing the token here is what makes the next
      // attempt log in again instead of repeating the same 401.
      this._accessToken = null;
      throw new OrchestratorError("Orchestrator SSE 401 — token hết hạn", 401, null);
    }
    if (!response.ok || !response.body) {
      throw new OrchestratorError(
        `Orchestrator SSE connect thất bại: ${response.status} ${response.statusText}`,
        response.status,
        null
      );
    }

    logger.info("orchestrator metadata stream connected");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      while (!this._stopped) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          for (const line of frame.split("\n")) {
            if (!line.startsWith("data:")) continue;
            const jsonText = line.slice(5).trim();
            if (!jsonText) continue;
            let parsedEvent;
            try {
              parsedEvent = JSON.parse(jsonText);
            } catch (err) {
              logger.warn("could not parse orchestrator metadata frame", {
                error: err?.message,
                frame: jsonText.slice(0, 200),
              });
              continue;
            }
            try {
              onEvent(parsedEvent);
            } catch (err) {
              // Distinct from the parse failure above: this is a bug in the
              // handler itself, not a malformed frame — mislabeling it as a
              // parse error would send debugging in the wrong direction.
              logger.error("orchestrator metadata event handler threw", {
                error: err?.message,
                event_type: parsedEvent?.event_type,
              });
            }
          }
        }
      }
    } finally {
      try {
        reader.releaseLock();
      } catch {
        // Already released or the stream already errored — nothing to do.
      }
    }
  }
}

module.exports = { OrchestratorClient, OrchestratorError };
