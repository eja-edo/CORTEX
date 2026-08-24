"use strict";

/**
 * Tests for `toMezonContent`/`splitMezonContent` — see `mezon/markdown.js`'s
 * file docstring for why this is raw pass-through now, not a Markdown-to-
 * Mezon-styling converter: the only behaviour left to pin is "the AI's
 * text comes back byte-identical in `t`" and "a message over Mezon's
 * character cap gets split, never truncated or corrupted."
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { toMezonContent, splitMezonContent } = require("../src/mezon/markdown");

test("markdown passes through untouched — no styling, no stripping, no attachments", () => {
  const md = "# Heading\n\n**bold** and `code` and a | table | line |\n\n- một\n- hai";
  assert.deepEqual(toMezonContent(md), { t: md });
});

test("empty and nullish input round-trip to an empty t", () => {
  assert.deepEqual(toMezonContent(""), { t: "" });
  assert.deepEqual(toMezonContent(null), { t: "" });
  assert.deepEqual(toMezonContent(undefined), { t: "" });
});

test("splitMezonContent returns a single chunk, identical to toMezonContent, when the whole thing fits", () => {
  const md = "Một đoạn văn ngắn, dưới giới hạn ký tự.";
  const chunks = splitMezonContent(md);
  assert.equal(chunks.length, 1);
  assert.deepEqual(chunks[0], toMezonContent(md));
});

test("splitMezonContent returns [{t: \"\"}] for empty input, never an empty array", () => {
  assert.deepEqual(splitMezonContent(""), [{ t: "" }]);
  assert.deepEqual(splitMezonContent(null), [{ t: "" }]);
  assert.deepEqual(splitMezonContent(undefined), [{ t: "" }]);
});

test("splitMezonContent cuts at the last newline within budget once the budget is exceeded, every chunk under the limit", () => {
  const lines = Array.from({ length: 30 }, (_, i) => `Dòng số ${i} với một chút nội dung để có độ dài.`);
  const md = lines.join("\n");
  const maxChars = 200; // small, deterministic budget — forces several cuts

  const chunks = splitMezonContent(md, maxChars);

  assert.ok(chunks.length > 1, "30 lines at a 200-char budget must produce more than one message");
  for (const chunk of chunks) {
    assert.ok(chunk.t.length <= maxChars, `every chunk must fit the budget: ${JSON.stringify(chunk)}`);
  }
  // Rejoining with "\n" (the newline consumed as the cut point) must
  // reconstruct the original text exactly — nothing dropped, duplicated,
  // or reordered.
  assert.equal(chunks.map((c) => c.t).join("\n"), md);
});

test("splitMezonContent cuts at the character limit itself when a single line is longer than the whole budget", () => {
  const longLine = "x".repeat(500); // one line, no newline inside it
  const chunks = splitMezonContent(longLine, 100);

  assert.ok(chunks.length > 1, "a line longer than the budget must still be split, not sent oversized");
  for (const chunk of chunks) {
    assert.ok(chunk.t.length <= 100);
  }
  assert.equal(chunks.map((c) => c.t).join(""), longLine, "content must be intact when rejoined, even though it was cut mid-line");
});

test("splitMezonContent never drops content across many chunks", () => {
  const paragraphs = Array.from({ length: 45 }, (_, i) => `Đây là đoạn số ${i} với đủ nội dung để tổng độ dài vượt quá giới hạn một tin nhắn.`);
  const md = paragraphs.join("\n\n");

  const chunks = splitMezonContent(md, 500);
  const rejoined = chunks.map((c) => c.t).join("\n");
  for (const p of paragraphs) {
    assert.ok(rejoined.includes(p), `paragraph must survive somewhere: "${p}"`);
  }
});
