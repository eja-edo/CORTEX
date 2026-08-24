"use strict";

/**
 * Minimal structured logging.
 *
 * `redact` exists because the two most useful things to log — the config
 * and an outgoing request — are also the two most likely to carry the
 * internal API key, which grants the ability to act as any user. A log
 * line is forever; scrubbing at the boundary is cheaper than auditing
 * every call site.
 */

// Reads the environment directly rather than importing `config`, which
// validates credentials and refuses to load without them. Logging is used
// by every module including the pure ones, so depending on validated
// config here would mean unit tests of argument parsing could not run
// without a bot token — a test suite that needs production secrets is one
// that stops being run.
const LEVELS = { error: 0, warn: 1, info: 2, debug: 3 };
const threshold = LEVELS[process.env.LOG_LEVEL] ?? LEVELS.info;

/**
 * Field names whose values must never be logged.
 *
 * Matched against the name with separators stripped, so `api_key`,
 * `apiKey`, `X-Internal-API-Key` and `APIKEY` all collapse to `apikey` and
 * are caught by one entry.
 *
 * A bare `key` used to be on this list and was actively harmful:
 * `reason_key` matched it, so every delivery log said `«redacted»` for the
 * one field that says *why* Cortex spoke — the single most useful thing
 * when debugging a notification. Redaction that hides ordinary data
 * teaches people to distrust the logs, which is worse than the leak it was
 * guarding against. Only patterns that name a credential belong here.
 */
const SECRET_FRAGMENTS = [
  "token",
  "secret",
  "password",
  "authorization",
  "apikey",
  "privatekey",
  "credential",
];

function isSecretName(name) {
  const normalized = String(name).toLowerCase().replace(/[^a-z0-9]/g, "");
  if (normalized === "key") return true;
  return SECRET_FRAGMENTS.some((fragment) => normalized.includes(fragment));
}

function redact(value, depth = 0) {
  if (depth > 4 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => redact(v, depth + 1));
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    out[k] = isSecretName(k) ? "«redacted»" : redact(v, depth + 1);
  }
  return out;
}

function emit(level, message, context) {
  if (LEVELS[level] > threshold) return;
  const line = `${new Date().toISOString()} | ${level.toUpperCase().padEnd(5)} | ${message}`;
  if (context === undefined) {
    console.log(line);
  } else {
    console.log(line, JSON.stringify(redact(context)));
  }
}

const logger = {
  error: (m, c) => emit("error", m, c),
  warn: (m, c) => emit("warn", m, c),
  info: (m, c) => emit("info", m, c),
  debug: (m, c) => emit("debug", m, c),
};

module.exports = { logger, redact, isSecretName };
