"use strict";

/**
 * Configuration, validated once at startup.
 *
 * Everything required is checked here and the process refuses to start if
 * something is missing. A bot that boots with a blank Cortex URL looks
 * healthy, answers "ready", and then fails one user at a time in ways that
 * surface as "the bot is broken" hours later.
 */

require("dotenv").config();

function required(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Thiếu biến môi trường bắt buộc: ${name} (xem .env.example)`);
  }
  return value;
}

function optional(name, fallback) {
  const value = process.env[name];
  return value === undefined || value === "" ? fallback : value;
}

function number(name, fallback) {
  const raw = optional(name, null);
  if (raw === null) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${name} phải là số, nhận được: ${raw}`);
  }
  return parsed;
}

/** `"false"`/`"0"`/`"no"` are the only ways to turn something off — an
 *  unset or empty variable falls back rather than reading as `false`, so
 *  a half-filled `.env` never silently disables a default-on feature. */
function boolean(name, fallback) {
  const raw = optional(name, null);
  if (raw === null) return fallback;
  return !["false", "0", "no", "off"].includes(String(raw).trim().toLowerCase());
}

const config = {
  mezon: {
    // botId is required by the SDK constructor itself — the Mezon docs'
    // `new MezonClient({ token })` example throws.
    botId: required("MEZON_BOT_ID"),
    token: required("MEZON_BOT_TOKEN"),
  },

  cortex: {
    baseUrl: optional("CORTEX_API_URL", "http://localhost:8000").replace(/\/$/, ""),
    // Grants the ability to act as any user, so it never leaves the
    // internal network and is never echoed into a chat message or a log.
    internalApiKey: required("CORTEX_INTERNAL_API_KEY"),
    timeoutMs: number("CORTEX_TIMEOUT_MS", 30000),
  },

  server: {
    // Where the backend's MezonAdapter posts notifications.
    port: number("BOT_PORT", 8100),
    host: optional("BOT_HOST", "127.0.0.1"),
  },

  bot: {
    commandPrefix: optional("BOT_COMMAND_PREFIX", "*"),
    // Leave the "🧠 Đã suy nghĩ" transcript message standing once the
    // turn ends, instead of deleting it the way the web UI unmounts its
    // timeline. On by default because on Mezon it is the only way to see
    // what the agent reasoned and which tools it ran — the web has a
    // conversation pane and a devtools network tab to fall back on, a DM
    // has neither. `BOT_KEEP_THINKING=false` restores web parity: the
    // transcript message is deleted, leaving only the answer.
    keepThinking: boolean("BOT_KEEP_THINKING", true),
  },

  // `*test svg` only — not required to start the bot, since nothing else
  // uses object storage. `endpoint` is where THIS process reaches MinIO
  // (same machine, so plain localhost is fine); `publicBaseUrl` is what
  // Mezon's own servers fetch the resulting image from, which localhost
  // can never be for them — see mezon/storage.js's docstring.
  storage: {
    endpoint: optional("MINIO_ENDPOINT", null),
    accessKey: optional("MINIO_ACCESS_KEY", null),
    secretKey: optional("MINIO_SECRET_KEY", null),
    bucket: optional("MINIO_BUCKET", "cortex-recordings"),
    publicBaseUrl: optional("MINIO_PUBLIC_URL", null)?.replace(/\/$/, "") ?? null,
  },

  logLevel: optional("LOG_LEVEL", "info"),
};

module.exports = { config };
