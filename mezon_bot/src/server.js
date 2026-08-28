"use strict";

/**
 * The inbound half of notification delivery.
 *
 * Cortex's `MezonAdapter` (backend, Python) cannot talk to Mezon — the SDK
 * is TypeScript-only — so it POSTs here and this process does the DM. The
 * whole contract lives in the HTTP status code, because that is what the
 * delivery layer's retry machinery reads:
 *
 *   2xx  → sent, delivery closed
 *   410  → dead address; the backend DISABLES the user's channel
 *   408/429/5xx → retryable, backed off and retried up to DELIVERY_MAX_ATTEMPTS
 *   other 4xx → permanent failure, no retry
 *
 * Those mappings are not decoration: returning the wrong one either drops
 * a notification that would have succeeded on retry, or permanently
 * unlinks a user's account over a transient blip.
 *
 * Built on `node:http` rather than a framework. One route, one auth check
 * — a dependency here would be more surface than substance, and this
 * process already holds a key that can act as any user.
 */

const http = require("node:http");
const crypto = require("node:crypto");

const { config } = require("./config");
const { logger } = require("./logger");
const { notification: notificationEmbed } = require("./mezon/embed");

// Enough for a notification with content blocks; anything larger is a bug
// or an attack, and buffering it would be the vulnerability.
const MAX_BODY_BYTES = 256 * 1024;

/**
 * Constant-time key comparison.
 *
 * `===` on secrets leaks their prefix through timing. The length guard
 * before it is required because `timingSafeEqual` throws on mismatched
 * lengths — leaking length only, which is not the secret.
 */
function keyMatches(provided) {
  if (typeof provided !== "string") return false;
  const a = Buffer.from(provided);
  const b = Buffer.from(config.cortex.internalApiKey);
  if (a.length !== b.length) return false;
  return crypto.timingSafeEqual(a, b);
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY_BYTES) {
        reject(Object.assign(new Error("payload too large"), { statusCode: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
    req.on("error", reject);
  });
}

function send(res, status, payload) {
  const body = JSON.stringify(payload ?? {});
  res.writeHead(status, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

/**
 * Does this error mean the recipient is unreachable *for good*?
 *
 * Deliberately conservative. Mezon publishes no error taxonomy, so
 * anything not recognised is treated as retryable — the delivery layer
 * caps attempts anyway, whereas a wrong `dead_address` verdict disables a
 * working channel and the user simply stops hearing from Cortex with no
 * indication why. Over-retrying costs a few requests; over-disabling
 * costs the feature.
 */
function isPermanentlyUnreachable(err) {
  const message = String(err?.message ?? err).toLowerCase();
  return (
    message.includes("can not get dmchannelid") ||
    message.includes("user not found") ||
    message.includes("blocked")
  );
}

function createServer({ gateway }) {
  return http.createServer(async (req, res) => {
    // Liveness for a process manager. Intentionally before auth: a health
    // probe that needs the internal key would mean shipping the key to
    // whatever does the probing.
    if (req.method === "GET" && req.url === "/health") {
      return send(res, 200, { ok: true, bot: gateway?.botId ?? null });
    }

    if (req.method !== "POST" || req.url !== "/internal/deliver") {
      return send(res, 404, { detail: "not found" });
    }

    if (!keyMatches(req.headers["x-internal-api-key"])) {
      logger.warn("rejected delivery with bad internal key", {
        remote: req.socket.remoteAddress,
      });
      // 403 is a non-retryable 4xx by the adapter's mapping, which is
      // right: a wrong key will still be wrong in thirty seconds.
      return send(res, 403, { detail: "invalid internal api key" });
    }

    let payload;
    try {
      payload = JSON.parse(await readBody(req));
    } catch (err) {
      const status = err?.statusCode ?? 400;
      return send(res, status, { detail: `bad request: ${err?.message}` });
    }

    const {
      mezon_user_id: mezonUserId,
      notification_id: notificationId,
      // Có mặt khi lời nhắc thuộc phạm vi dự án (DESIGN 8.1). Backend đã
      // quyết định phạm vi; bot chỉ chọn đường gửi theo trường này và
      // không tự suy luận gì thêm.
      mezon_channel_id: mezonChannelId,
    } = payload ?? {};
    if (!mezonUserId || !payload?.title) {
      // Malformed and will stay malformed — permanent, so the backend
      // stops retrying it.
      return send(res, 400, { detail: "mezon_user_id and title are required" });
    }

    try {
      // Dự án đăng vào channel chung; việc cá nhân vào DM. Đây là chỗ duy
      // nhất trong bot phân biệt hai loại, và nó phân biệt bằng dữ liệu
      // backend gửi xuống, không bằng nội dung lời nhắc.
      const sent = mezonChannelId
        ? await gateway.sendToChannel(mezonChannelId, notificationEmbed(payload))
        : await gateway.sendDirectMessage(mezonUserId, notificationEmbed(payload));
      logger.info("notification delivered", {
        notification_id: notificationId,
        mezon_user_id: mezonUserId,
        mezon_channel_id: mezonChannelId ?? null,
        level: payload.attention_level,
        reason_key: payload.reason_key,
        message_id: sent?.id ?? null,
      });
      return send(res, 200, { delivered: true, message_id: sent?.id ?? null });
    } catch (err) {
      const permanent = isPermanentlyUnreachable(err);
      logger.error("notification delivery failed", {
        notification_id: notificationId,
        mezon_user_id: mezonUserId,
        permanent,
        error: err?.message ?? String(err),
      });
      // 410 is the agreed signal for "stop trying this address"; the
      // backend disables the channel on it.
      return send(res, permanent ? 410 : 502, { detail: String(err?.message ?? err) });
    }
  });
}

function startServer({ gateway }) {
  const server = createServer({ gateway });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(config.server.port, config.server.host, () => {
      logger.info("delivery server listening", {
        host: config.server.host,
        port: config.server.port,
      });
      resolve(server);
    });
  });
}

module.exports = { createServer, startServer, isPermanentlyUnreachable, keyMatches };
