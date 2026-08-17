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
  },

  logLevel: optional("LOG_LEVEL", "info"),
};

module.exports = { config };
