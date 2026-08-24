"use strict";

/**
 * Tests for the delivery endpoint.
 *
 * The status code *is* the contract: the backend's MezonAdapter reads it
 * to decide between "done", "retry later", and "disable this user's
 * channel forever". Every test here pins one of those decisions, because
 * getting one wrong is invisible locally and expensive in production —
 * either a nudge is dropped that a retry would have delivered, or a
 * working account is unlinked over a transient blip.
 *
 * The gateway is faked. What is under test is the HTTP contract, not
 * Mezon, and requiring a live socket would make these untestable in CI.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const { createServer, isPermanentlyUnreachable } = require("../src/server");

const KEY = process.env.CORTEX_INTERNAL_API_KEY;

function fakeGateway({ send } = {}) {
  const calls = [];
  return {
    botId: "test-bot",
    calls,
    async sendDirectMessage(userId, content) {
      calls.push({ userId, content });
      if (send) return send(userId, content);
      return { id: "msg-1" };
    },
  };
}

async function withServer(gateway, fn) {
  const server = createServer({ gateway });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    return await fn(`http://127.0.0.1:${port}`);
  } finally {
    server.close();
  }
}

function deliver(base, body, { key = KEY } = {}) {
  return fetch(`${base}/internal/deliver`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(key === null ? {} : { "X-Internal-API-Key": key }),
    },
    body: JSON.stringify(body),
  });
}

const VALID = {
  mezon_user_id: "user-42",
  notification_id: "notif-1",
  title: "Task quá hạn",
  body: "Nộp báo cáo tuần",
  attention_level: "ask",
  reason_key: "task.overdue",
};

test("a valid delivery is sent and answered 200", async () => {
  const gateway = fakeGateway();
  await withServer(gateway, async (base) => {
    const res = await deliver(base, VALID);
    assert.equal(res.status, 200);
    assert.equal((await res.json()).delivered, true);
    assert.equal(gateway.calls.length, 1);
    assert.equal(gateway.calls[0].userId, "user-42");
    // The rendered embed, not raw text — the level and reason have to
    // survive the trip or the Gate's judgement is lost at the last step.
    const embed = gateway.calls[0].content.embed[0];
    assert.match(embed.title, /Task quá hạn/);
    assert.equal(embed.description, "Nộp báo cáo tuần");
  });
});

test("a wrong key is 403, which the adapter treats as non-retryable", async () => {
  const gateway = fakeGateway();
  await withServer(gateway, async (base) => {
    const res = await deliver(base, VALID, { key: "wrong-key-000" });
    assert.equal(res.status, 403);
    assert.equal(gateway.calls.length, 0, "must not send before authenticating");
  });
});

test("a missing key is rejected too", async () => {
  const gateway = fakeGateway();
  await withServer(gateway, async (base) => {
    const res = await deliver(base, VALID, { key: null });
    assert.equal(res.status, 403);
    assert.equal(gateway.calls.length, 0);
  });
});

test("a malformed payload is 400 — permanent, not retried forever", async () => {
  const gateway = fakeGateway();
  await withServer(gateway, async (base) => {
    const missingUser = await deliver(base, { title: "x" });
    assert.equal(missingUser.status, 400);

    const missingTitle = await deliver(base, { mezon_user_id: "u1" });
    assert.equal(missingTitle.status, 400);

    assert.equal(gateway.calls.length, 0);
  });
});

test("a transient send failure is 502 so the backend retries", async () => {
  const gateway = fakeGateway({
    send: () => {
      throw new Error("socket hang up");
    },
  });
  await withServer(gateway, async (base) => {
    const res = await deliver(base, VALID);
    // 502 is in the adapter's retry range. An unrecognised error must
    // never disable a channel: over-retrying costs requests, over-
    // disabling costs the feature.
    assert.equal(res.status, 502);
  });
});

test("an unreachable recipient is 410 so the channel gets disabled", async () => {
  const gateway = fakeGateway({
    send: () => {
      throw new Error("Can not get dmChannelId for this user 123!");
    },
  });
  await withServer(gateway, async (base) => {
    const res = await deliver(base, VALID);
    assert.equal(res.status, 410);
  });
});

test("health needs no key — a probe should not have to hold the secret", async () => {
  await withServer(fakeGateway(), async (base) => {
    const res = await fetch(`${base}/health`);
    assert.equal(res.status, 200);
    assert.equal((await res.json()).ok, true);
  });
});

test("unknown routes are 404", async () => {
  await withServer(fakeGateway(), async (base) => {
    const res = await fetch(`${base}/whatever`);
    assert.equal(res.status, 404);
  });
});

test("only recognised errors count as permanently unreachable", () => {
  assert.equal(isPermanentlyUnreachable(new Error("Can not get dmChannelId")), true);
  assert.equal(isPermanentlyUnreachable(new Error("user not found")), true);
  assert.equal(isPermanentlyUnreachable(new Error("bot was blocked by the user")), true);
  // Everything else stays retryable, on purpose.
  assert.equal(isPermanentlyUnreachable(new Error("ETIMEDOUT")), false);
  assert.equal(isPermanentlyUnreachable(new Error("503 upstream")), false);
  assert.equal(isPermanentlyUnreachable(undefined), false);
});
