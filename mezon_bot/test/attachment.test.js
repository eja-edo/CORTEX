"use strict";

/**
 * Tests for `normalizeAttachment` — see `src/mezon/attachment.js`'s
 * docstring for the crash this exists to prevent (an `undefined` field
 * makes `mezon-sdk`'s protobuf encoder throw mid-write and take the
 * socket connection down with it).
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { normalizeAttachment } = require("../src/mezon/attachment");
const { MessageAttachment } = require("mezon-sdk/dist/cjs/api/api");

test("normalizeAttachment fills in every ApiMessageAttachment field, not just the ones given", () => {
  const result = normalizeAttachment({ url: "https://x.test/a.png", filetype: "image/png", filename: "a.png" });
  assert.deepEqual(result, {
    url: "https://x.test/a.png",
    filetype: "image/png",
    filename: "a.png",
    size: 0,
    width: 0,
    height: 0,
    thumbnail: "",
    duration: 0,
  });
});

test("normalizeAttachment with no argument is still a fully-shaped, encodable attachment", () => {
  const result = normalizeAttachment();
  assert.deepEqual(result, {
    url: "",
    filetype: "",
    filename: "",
    size: 0,
    width: 0,
    height: 0,
    thumbnail: "",
    duration: 0,
  });
});

test("a normalized attachment survives mezon-sdk's own protobuf encoder without throwing", () => {
  // This is the actual bug this module fixes: an attachment shaped as
  // just {url, filetype, filename} makes MessageAttachment.encode throw
  // (`.string(undefined)` inside protobufjs) the moment it reaches an
  // untouched field like `thumbnail`. Encoding for real, against the
  // installed SDK, is the only check that actually proves the fix.
  const attachment = normalizeAttachment({ url: "https://x.test/a.png", filetype: "image/png", filename: "a.png" });
  assert.doesNotThrow(() => {
    const bytes = MessageAttachment.encode(attachment).finish();
    assert.ok(bytes.length > 0);
  });
});
