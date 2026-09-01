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

/**
 * Suggestions for a mistyped command.
 *
 * The case that prompted this: `*models` answered "no such command, type
 * *help" — technically true, useless in practice. Someone who typed
 * `*models` already knows which command they want.
 */

function makeSuggestRegistry() {
  const registry = makeRegistry();
  for (const name of ["help", "ping", "link", "today", "next", "tasks", "new", "mute", "inbox", "model", "test"]) {
    // `help` carries a one-letter alias, as the real bot's does. Without one
    // here the first version of this suite passed while the live registry
    // answered `*halp` with `*h`.
    const aliases = name === "help" ? ["h"] : [];
    registry.register({ name, aliases, description: "x", run: async () => {} });
  }
  return registry;
}

test("a plural of a real command suggests that command", () => {
  assert.deepEqual(makeSuggestRegistry().suggest("models"), ["model"]);
});

test("a one-letter typo suggests the command it missed", () => {
  assert.deepEqual(makeSuggestRegistry().suggest("halp"), ["help"]);
});

test("a one-letter alias never wins on the strength of one shared letter", () => {
  // `*halp` starts with `h`, so a prefix rule that only measures the typed
  // side ranks the alias above `help` itself.
  assert.deepEqual(makeSuggestRegistry().suggest("halp"), ["help"]);
  assert.equal(makeSuggestRegistry().suggest("hmmmm").includes("h"), false);
});

test("a different command is not offered as a fix for a short name", () => {
  // `ping` → `link` is two edits on a four-letter name. Accepting it would
  // not correct a typo, it would propose an unrelated command.
  assert.equal(makeSuggestRegistry().suggest("ping").includes("link"), false);
});

test("gibberish suggests nothing rather than reaching for the nearest name", () => {
  assert.deepEqual(makeSuggestRegistry().suggest("zzzzzzzz"), []);
});

test("suggestions are capped and ordered deterministically", () => {
  const registry = makeRegistry();
  for (const name of ["task", "tasks", "tasty", "test"]) {
    registry.register({ name, description: "x", run: async () => {} });
  }

  // Three names share the prefix; only two are offered, alphabetically, so
  // the same typo always gets the same answer.
  assert.deepEqual(registry.suggest("tas"), ["task", "tasks"]);
});

test("one command is offered once even when its alias also matches", () => {
  const command = { name: "note", aliases: ["notes"], description: "x", run: async () => {} };
  const registry = makeRegistry().register(command);

  assert.deepEqual(registry.suggest("notess"), ["note"]);
});

test("the unknown-command reply names the suggestion", async () => {
  const registry = makeSuggestRegistry();
  const { ctx, replies } = makeCtx();

  const result = await registry.dispatch({ name: "models", args: "" }, ctx);

  assert.deepEqual(result.suggestions, ["model"]);
  assert.match(replies[0], /Ý bạn là có phải là `\*model`\?/);
  // The catalogue pointer survives: a wrong guess must still leave a way out.
  assert.match(replies[0], /\*help/);
});

test("with nothing close, the reply falls back to the catalogue alone", async () => {
  const registry = makeSuggestRegistry();
  const { ctx, replies } = makeCtx();

  const result = await registry.dispatch({ name: "zzzzzzzz", args: "" }, ctx);

  assert.deepEqual(result.suggestions, []);
  assert.equal(/Ý bạn là/.test(replies[0]), false);
  assert.match(replies[0], /\*help/);
});

/**
 * The clan-icon form, `:name:`.
 *
 * Mezon shows an icon picker as soon as someone types `:`, so naming clan
 * icons after commands turns that picker into command autocomplete. The
 * risk the tests below pin down is the other half: every ordinary emoji is
 * written the same way, and the bot must not start answering smileys.
 */

test("an icon named after a command runs that command", () => {
    assert.deepEqual(makeSuggestRegistry().parse(":today:"), { name: "today", args: "" });
});

test("an icon carries arguments like the prefix form does", () => {
    assert.deepEqual(makeSuggestRegistry().parse(":new: mua sữa chiều nay"), {
        name: "new",
        args: "mua sữa chiều nay",
    });
});

test("an icon that is not a command is left for the AI", () => {
    // The case from live traffic. `:pepe_joy:` is a person being cheerful;
    // parsing it as a command means answering them with an error.
    assert.equal(makeSuggestRegistry().parse(":pepe_joy:"), null);
    assert.equal(makeSuggestRegistry().parse(":smile:"), null);
});

test("an icon mid-sentence is conversation, not a command", () => {
    assert.equal(makeSuggestRegistry().parse("ok :today: nhé"), null);
});

test("the icon form resolves aliases and ignores case", () => {
    assert.deepEqual(makeSuggestRegistry().parse(":H:"), { name: "h", args: "" });
});

test("a lone colon or an empty icon is not a command", () => {
    assert.equal(makeSuggestRegistry().parse(":"), null);
    assert.equal(makeSuggestRegistry().parse("::"), null);
});

test("the prefix form still works unchanged alongside icons", () => {
    assert.deepEqual(makeSuggestRegistry().parse("*today"), { name: "today", args: "" });
    assert.deepEqual(makeSuggestRegistry().parse("*models"), { name: "models", args: "" });
});
