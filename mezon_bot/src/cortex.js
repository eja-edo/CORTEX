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
