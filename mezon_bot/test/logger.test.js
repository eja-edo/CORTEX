"use strict";

/**
 * Tests for log redaction.
 *
 * Two failure modes, and the second is the one that actually bit:
 * leaking a credential, and hiding ordinary data. A blanket /key/ match
 * redacted `reason_key` — the field that says *why* Cortex spoke — so
 * every delivery log lost the most useful thing in it. Redaction that
 * swallows normal fields teaches people to stop trusting the logs.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { redact, isSecretName } = require("../src/logger");

test("credentials are redacted in every spelling", () => {
  for (const name of [
    "token",
    "MEZON_BOT_TOKEN",
    "botToken",
    "api_key",
    "apiKey",
    "X-Internal-API-Key",
    "CORTEX_INTERNAL_API_KEY",
    "password",
    "client_secret",
    "authorization",
    "privateKey",
    "key",
  ]) {
    assert.equal(isSecretName(name), true, `${name} must be redacted`);
  }
});

test("ordinary fields containing 'key' are NOT redacted", () => {
  // The regression: reason_key is the reason a notification was sent, and
  // it is exactly what a user can switch off in Settings. Hiding it makes
  // delivery logs useless.
  for (const name of ["reason_key", "reasonKey", "keyboard", "monkey", "button_id"]) {
    assert.equal(isSecretName(name), false, `${name} must stay visible`);
  }
});

test("redact walks nested objects and arrays", () => {
  const out = redact({
    reason_key: "task.overdue",
    cortex: { internalApiKey: "s3cret", baseUrl: "http://localhost:8000" },
    items: [{ token: "abc", label: "ok" }],
  });

  assert.equal(out.reason_key, "task.overdue");
  assert.equal(out.cortex.internalApiKey, "«redacted»");
  assert.equal(out.cortex.baseUrl, "http://localhost:8000");
  assert.equal(out.items[0].token, "«redacted»");
  assert.equal(out.items[0].label, "ok");
});

test("redact leaves primitives alone", () => {
  assert.equal(redact("plain"), "plain");
  assert.equal(redact(42), 42);
  assert.equal(redact(null), null);
});
