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

const SECRET_KEYS = /token|key|secret|password|authorization/i;

function redact(value, depth = 0) {
  if (depth > 4 || value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map((v) => redact(v, depth + 1));
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    out[k] = SECRET_KEYS.test(k) ? "«redacted»" : redact(v, depth + 1);
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

module.exports = { logger, redact };
