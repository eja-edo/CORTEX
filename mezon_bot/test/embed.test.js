"use strict";

/**
 * Tests for `mezon/embed.js`'s `fieldsToEmbed`/`withTableEmbeds` — the
 * seam between `markdown.js`'s SDK-agnostic `tables` data and a real
 * `InteractiveBuilder` embed object. See `markdown.js`'s file docstring
 * for why a table became embed fields at all.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { fieldsToEmbed, withTableEmbeds, DEFAULT_COLOR } = require("../src/mezon/embed");

const ZERO_WIDTH_SPACE = "\u200B";

const SAMPLE_FIELDS = [
  { name: "Tên", value: ZERO_WIDTH_SPACE, inline: true },
  { name: ZERO_WIDTH_SPACE, value: "An", inline: true },
];

test("fieldsToEmbed produces a real embed object carrying exactly the given fields", () => {
  const embed = fieldsToEmbed(SAMPLE_FIELDS);
  assert.deepEqual(embed.fields, SAMPLE_FIELDS);
  assert.equal(embed.color, DEFAULT_COLOR);
});

test("fieldsToEmbed sets no title — a table embed sits inline with a message's own text, not as its own titled card", () => {
  const embed = fieldsToEmbed(SAMPLE_FIELDS);
  assert.equal(embed.title, "");
});

test("withTableEmbeds turns content.tables into content.embed, one embed per table, and drops the tables key", () => {
  const content = {
    t: "một đoạn văn",
    mk: [{ type: "b", s: 0, e: 3 }],
    tables: [{ fields: SAMPLE_FIELDS }, { fields: [{ name: "X", value: "1", inline: true }] }],
  };
  const result = withTableEmbeds(content);

  assert.equal(result.tables, undefined, "tables must not survive into the SDK-facing content");
  assert.equal(result.t, "một đoạn văn", "t must pass through untouched");
  assert.deepEqual(result.mk, content.mk, "mk must pass through untouched");
  assert.equal(result.embed.length, 2);
  assert.deepEqual(result.embed[0].fields, SAMPLE_FIELDS);
  assert.equal(result.embed[1].fields[0].name, "X");
});

test("withTableEmbeds passes content through unchanged when there is no table", () => {
  const content = { t: "chỉ là chữ", mk: [{ type: "b", s: 0, e: 3 }] };
  const result = withTableEmbeds(content);
  assert.deepEqual(result, content);
  assert.equal(result.embed, undefined);
});

test("withTableEmbeds handles an empty tables array the same as no tables at all", () => {
  const content = { t: "x", tables: [] };
  const result = withTableEmbeds(content);
  assert.equal(result.embed, undefined);
  assert.equal(result.tables, undefined);
});

// ---------------------------------------------------------------------------
// notification() — digest detail reaching a DM
// ---------------------------------------------------------------------------
//
// The digest reasons (day.plan, day.review, task.at_risk,
// task.blocked_cascade) keep `body` as a one-line summary and put the
// itemised detail in `content`, one text block per line, because the web
// renderer wraps each block in its own element. Chat has no such
// structure, so the bot rejoins them — without that a DM said "3 việc đến
// hạn hôm nay" and named none of them.

const { contentLines, notification } = require("../src/mezon/embed");

test("contentLines keeps the itemised text blocks", () => {
  const lines = contentLines(
    [
      { type: "text", text: "3 việc đến hạn hôm nay" },
      { type: "text", text: "Đến hạn hôm nay:" },
      { type: "text", text: "• Nộp hồ sơ thầu — hạn hôm nay 17:00" },
    ],
    "3 việc đến hạn hôm nay"
  );

  assert.deepEqual(lines, ["Đến hạn hôm nay:", "• Nộp hồ sơ thầu — hạn hôm nay 17:00"]);
});

test("contentLines drops the block that merely repeats body", () => {
  // The backend composes body as the summary line and puts it at the head
  // of content, so printing both would show it twice.
  assert.deepEqual(contentLines([{ type: "text", text: "same" }], "same"), []);
});

test("contentLines skips blocks chat cannot render", () => {
  const lines = contentLines(
    [
      { type: "image", url: "https://example.invalid/x.png" },
      { type: "code", content: "print(1)" },
      { type: "text", text: "• Việc A" },
    ],
    "summary"
  );

  assert.deepEqual(lines, ["• Việc A"]);
});

test("contentLines tolerates a notification with no content at all", () => {
  assert.deepEqual(contentLines(undefined, "summary"), []);
  assert.deepEqual(contentLines(null, "summary"), []);
  assert.deepEqual(contentLines("not-an-array", "summary"), []);
});

test("notification puts body and its detail lines in one description", () => {
  const built = notification({
    title: "Kế hoạch hôm nay",
    body: "3 việc đến hạn hôm nay",
    content: [
      { type: "text", text: "3 việc đến hạn hôm nay" },
      { type: "text", text: "• Nộp hồ sơ thầu" },
    ],
    attention_level: "inform",
    reason_key: "day.plan",
  });

  const rendered = JSON.stringify(built);
  assert.ok(rendered.includes("Nộp hồ sơ thầu"), "detail line must reach the DM");
  assert.ok(rendered.includes("day.plan"), "reason_key stays visible so it can be switched off");
});

test("notification still renders when only body is present", () => {
  const built = notification({
    title: "Quá hạn: Viết báo cáo Q3",
    body: "Trễ 3 ngày · hạn 21/08 17:00",
    attention_level: "recommend",
    reason_key: "task.overdue",
  });

  assert.ok(JSON.stringify(built).includes("Trễ 3 ngày"));
});
