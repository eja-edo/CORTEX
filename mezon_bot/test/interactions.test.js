"use strict";

/**
 * Tests for the form-reading rules.
 *
 * Every case here is a shape observed on the live gateway during M0, or a
 * direct consequence of one. They are regression tests for three specific
 * bugs that are easy to reintroduce because the correct behaviour is
 * counter-intuitive: `extra_data` is not always JSON, the actor is
 * `user_id` and not `sender_id`, and a missing field means "unchanged"
 * rather than "empty".
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  parseExtraData,
  parseButtonEvent,
  hasField,
  getText,
  getList,
  getNumber,
  getDate,
} = require("../src/mezon/interactions");

// Verbatim from probe-findings, a full form submission.
const REAL_SUBMIT =
  '{"p_text":"giá trị mặc định","p_textarea":"ssd","p_number":"1.5",' +
  '"p_select":"b","p_radio":"high","p_radio_multi":"y","p_date":"34343-12-22"}';

// Verbatim, after the multi-select `name` fix.
const REAL_MULTI = '{"p_text":"giá trị mặc định","p_radio_multi":["x","y","z"]}';

test("parses a real form submission", () => {
  const result = parseExtraData(REAL_SUBMIT);
  assert.equal(result.kind, "form");
  assert.equal(result.values.p_text, "giá trị mặc định");
  assert.equal(result.values.p_select, "b");
});

test("multi-select radio comes back as an array", () => {
  const result = parseExtraData(REAL_MULTI);
  assert.deepEqual(result.values.p_radio_multi, ["x", "y", "z"]);
});

test("a select-change event carries a bare value, not JSON", () => {
  // Observed: button_id "p_select", extra_data "a". A blind JSON.parse
  // throws here, which would mean an exception per dropdown interaction.
  const result = parseExtraData("a");
  assert.equal(result.kind, "scalar");
  assert.equal(result.scalar, "a");
  assert.deepEqual(result.values, {});
});

test("empty and missing extra_data are handled, not thrown", () => {
  assert.equal(parseExtraData("").kind, "empty");
  assert.equal(parseExtraData(undefined).kind, "empty");
  assert.equal(parseExtraData(null).kind, "empty");
});

test("isFormSubmission separates a submit from a dropdown change", () => {
  const submit = parseButtonEvent({
    button_id: "p_submit",
    extra_data: REAL_SUBMIT,
    user_id: "user-1",
    sender_id: "bot-1",
  });
  const dropdown = parseButtonEvent({
    button_id: "p_select",
    extra_data: "a",
    user_id: "user-1",
    sender_id: "bot-1",
  });

  assert.equal(submit.isFormSubmission, true);
  assert.equal(dropdown.isFormSubmission, false);
});

test("the actor is user_id, never sender_id", () => {
  // sender_id is the author of the message holding the button — always the
  // bot for our forms. Attributing actions to it credits the bot for
  // everything a user does.
  const event = parseButtonEvent({
    button_id: "p_submit",
    extra_data: REAL_SUBMIT,
    user_id: "human-42",
    sender_id: "bot-9",
  });
  assert.equal(event.actorId, "human-42");
  assert.equal(event.messageAuthorId, "bot-9");
});

test("an untouched field is absent, and absent is not empty", () => {
  const { values } = parseExtraData('{"a":"filled"}');
  assert.equal(hasField(values, "a"), true);
  assert.equal(hasField(values, "b"), false);
  // The distinction the caller must preserve: "b" was not cleared, it was
  // never touched.
  assert.equal(getText(values, "b"), null);
});

test("getList normalises single and multi radios to one shape", () => {
  assert.deepEqual(getList({ r: "high" }, "r"), ["high"]);
  assert.deepEqual(getList({ r: ["x", "y"] }, "r"), ["x", "y"]);
  assert.deepEqual(getList({}, "r"), []);
});

test("numeric inputs arrive as strings", () => {
  assert.equal(getNumber({ n: "1.5" }, "n"), 1.5);
  assert.equal(getNumber({ n: "" }, "n"), null);
  // Never NaN — a bad value must not propagate as a number.
  assert.equal(getNumber({ n: "abc" }, "n"), null);
  assert.equal(getNumber({}, "n"), null);
});

test("rejects the unvalidated date the platform actually sent", () => {
  // Observed verbatim: a real datepicker produced year 34343. The client
  // validates nothing, so this is the only place it gets caught.
  assert.equal(getDate({ d: "34343-12-22" }, "d"), null);
});

test("accepts a well-formed date and rejects impossible ones", () => {
  assert.equal(getDate({ d: "2026-08-17" }, "d"), "2026-08-17");
  assert.equal(getDate({ d: "2026-02-31" }, "d"), null); // passes range, does not exist
  assert.equal(getDate({ d: "2026-13-01" }, "d"), null);
  assert.equal(getDate({ d: "17/08/2026" }, "d"), null);
  assert.equal(getDate({}, "d"), null);
});
