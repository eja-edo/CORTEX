"use strict";

/**
 * Tests for command parsing and the link gate.
 *
 * The gate is the part worth testing: it is the single place that stops an
 * unlinked Mezon account from reaching commands that act on someone's
 * data. A per-handler check would be the kind that eventually gets
 * forgotten in one handler.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { CommandRegistry } = require("../src/commands/registry");

function makeRegistry() {
  return new CommandRegistry({ prefix: "*" });
}

function makeCtx(overrides = {}) {
  const replies = [];
  return {
    replies,
    ctx: {
      reply: async (content) => replies.push(content),
      identity: { linked: false },
      message: { senderId: "u1" },
      ...overrides,
    },
  };
}

test("parses a bare command", () => {
  assert.deepEqual(makeRegistry().parse("*ping"), { name: "ping", args: "" });
});

test("parses a command with arguments", () => {
  assert.deepEqual(makeRegistry().parse("*link 123456"), { name: "link", args: "123456" });
});

test("keeps the whole argument string intact", () => {
  // Handlers own their own argument grammar; splitting here would force
  // every multi-word argument through the router's idea of tokens.
  assert.deepEqual(makeRegistry().parse("*task tạo báo cáo tuần"), {
    name: "task",
    args: "tạo báo cáo tuần",
  });
});

test("is case-insensitive and tolerates surrounding whitespace", () => {
  assert.deepEqual(makeRegistry().parse("  *PING  "), { name: "ping", args: "" });
});

test("plain text is not a command", () => {
  // Returning null is what routes a message to the AI instead — the
  // default path for a DM.
  assert.equal(makeRegistry().parse("chào bạn"), null);
  assert.equal(makeRegistry().parse(""), null);
  assert.equal(makeRegistry().parse("*"), null);
});

test("unknown command answers instead of failing silently", async () => {
  const registry = makeRegistry();
  const { ctx, replies } = makeCtx();

  const result = await registry.dispatch({ name: "nope", args: "" }, ctx);

  assert.equal(result.unknown, true);
  assert.match(replies[0], /help/);
});

test("a command needing a link is refused for an unlinked account", async () => {
  let ran = false;
  const registry = makeRegistry().register({
    name: "secret",
    description: "x",
    requiresLink: true,
    run: async () => {
      ran = true;
    },
  });
  const { ctx, replies } = makeCtx({ identity: { linked: false } });

  const result = await registry.dispatch({ name: "secret", args: "" }, ctx);

  assert.equal(ran, false, "handler must not run for an unlinked account");
  assert.equal(result.unlinked, true);
  assert.match(replies[0], /chưa liên kết/);
});

test("the same command runs once linked", async () => {
  let ran = false;
  const registry = makeRegistry().register({
    name: "secret",
    description: "x",
    requiresLink: true,
    run: async () => {
      ran = true;
    },
  });
  const { ctx } = makeCtx({ identity: { linked: true, userId: "cortex-1" } });

  await registry.dispatch({ name: "secret", args: "" }, ctx);

  assert.equal(ran, true);
});

test("link itself works without a link, or nobody could ever link", async () => {
  let ran = false;
  const registry = makeRegistry().register({
    name: "link",
    description: "x",
    requiresLink: false,
    run: async () => {
      ran = true;
    },
  });
  const { ctx } = makeCtx({ identity: { linked: false } });

  await registry.dispatch({ name: "link", args: "123456" }, ctx);

  assert.equal(ran, true);
});

test("aliases resolve to the same command and list() does not repeat it", () => {
  const command = { name: "help", aliases: ["h"], description: "x", run: async () => {} };
  const registry = makeRegistry().register(command);

  assert.equal(registry.commands.get("h"), command);
  assert.equal(registry.list().length, 1);
});
