"use strict";

/**
 * Tests for message-scope classification.
 *
 * This exists because getting it wrong is silent. A bot that misreads a
 * group chat as a DM does not crash and logs nothing unusual — it just
 * answers every message in a room full of people, and the first feedback
 * is being muted. The rule is one line of code, so the guard has to be a
 * test rather than care.
 *
 * `_normalise` is exercised through a bare object rather than a live
 * gateway: it reads only the message, so a connection would add nothing
 * but a credential requirement.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MezonGateway } = require("../src/mezon/client");

// `_normalise` touches no instance state, so it can be borrowed directly.
// Constructing a MezonGateway would require validated config, and this
// test has no business needing a bot token.
const normalise = MezonGateway.prototype._normalise;

function message(overrides = {}) {
  return {
    content: { t: "xin chào" },
    sender_id: "user-1",
    channel_id: "chan-1",
    clan_id: "0",
    mode: 4,
    ...overrides,
  };
}

test("mode 4 is a one-to-one DM", () => {
  const result = normalise(message({ mode: 4 }));
  assert.equal(result.scope, "dm");
  assert.equal(result.isDirectMessage, true);
});

test("mode 3 is a group chat, NOT a DM", () => {
  // The bug this pins: a group chat also has clan_id "0", so any rule that
  // accepts clan_id === "0" as "direct message" sweeps groups in with DMs
  // and the bot answers everyone in the room.
  const result = normalise(message({ mode: 3, clan_id: "0" }));
  assert.equal(result.scope, "group");
  assert.equal(result.isDirectMessage, false);
});

test("mode 2 is a clan text channel", () => {
  const result = normalise(message({ mode: 2, clan_id: "1234" }));
  assert.equal(result.scope, "channel");
  assert.equal(result.isDirectMessage, false);
});

test("mode 5 is clan scope", () => {
  const result = normalise(message({ mode: 5, clan_id: "1234" }));
  assert.equal(result.scope, "clan");
  assert.equal(result.isDirectMessage, false);
});

test("mode 6 is a thread", () => {
  const result = normalise(message({ mode: 6, clan_id: "1234" }));
  assert.equal(result.scope, "thread");
  assert.equal(result.isDirectMessage, false);
});

test("clan_id '0' alone does not make something a DM", () => {
  // Stated as its own test because it is the exact wrong inference, and a
  // future reader is likely to reach for clan_id as the "obvious" check.
  for (const mode of [2, 3, 5, 6]) {
    const result = normalise(message({ mode, clan_id: "0" }));
    assert.equal(result.isDirectMessage, false, `mode ${mode} must not be a DM`);
  }
});

test("a missing mode is 'unknown', never a guess", () => {
  // Everything observed on live traffic carried a mode. If that changes,
  // the router logs an unknown scope rather than quietly picking one.
  const result = normalise(message({ mode: undefined }));
  assert.equal(result.scope, "unknown");
  assert.equal(result.isDirectMessage, false);
});

test("an unrecognised mode number is 'unknown'", () => {
  const result = normalise(message({ mode: 99 }));
  assert.equal(result.scope, "unknown");
  assert.equal(result.isDirectMessage, false);
});

test("normalise carries the fields the router needs", () => {
  const result = normalise(
    message({ username: "someone", display_name: "Someone Else" })
  );
  assert.equal(result.text, "xin chào");
  assert.equal(result.senderId, "user-1");
  assert.equal(result.channelId, "chan-1");
  assert.equal(result.username, "someone");
  assert.equal(result.displayName, "Someone Else");
});

test("empty message content becomes an empty string, not undefined", () => {
  // The command parser calls .trim() on this; undefined would throw inside
  // the handler where the cause is far from the symptom.
  const result = normalise(message({ content: undefined }));
  assert.equal(result.text, "");
});
