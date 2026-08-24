"use strict";

/**
 * Tests for `ThinkingTimeline` — the Mezon rendering of the web UI's
 * thinking timeline, in isolation from the throttle and the router.
 * Parity with `useAgentStream.ts`/`ToolExecutionIndicator.tsx` is the
 * point of most of these, so each names the web behaviour it mirrors.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { ThinkingTimeline, toolSemanticDescription, toolResultSummary } = require("../src/mezon/thinking");

test("an untouched timeline renders nothing at all — not a bare header", () => {
  const timeline = new ThinkingTimeline();
  assert.equal(timeline.isEmpty(), true);
  assert.equal(timeline.render(), "");
});

test("reasoning tokens accumulate into one segment, rendered as a quoted block", () => {
  const timeline = new ThinkingTimeline();
  timeline.reasoning("Người dùng hỏi ");
  timeline.reasoning("về cuộc họp.");

  const rendered = timeline.render();
  assert.match(rendered, /🧠/);
  assert.match(rendered, /> Người dùng hỏi về cuộc họp\./, "the two chunks must join into one line, not two entries");
});

test("a tool call starts a new segment, and the one before it stays whole", async () => {
  // Mirrors `flushPendingThinking()` on tool_start in useAgentStream.ts:
  // reasoning after a tool call is a new step, not a continuation. Both
  // segments render in full — an earlier version collapsed the settled
  // one to its opening line, which is what made the Mezon view read as a
  // summary of the thinking rather than the thinking itself.
  const timeline = new ThinkingTimeline();
  const longThought = `Mở đầu suy nghĩ rất dài${" thêm chữ".repeat(40)}`;
  timeline.reasoning(longThought);
  timeline.toolStart("search_notes", { query: "họp" });
  timeline.toolResult("search_notes", { result: { notes: [1, 2, 3] }, success: true });
  timeline.reasoning("Có 3 kết quả, tóm tắt lại.");

  const rendered = timeline.render();
  assert.ok(rendered.includes(longThought), "the settled segment must survive in full");
  assert.match(rendered, /> Có 3 kết quả, tóm tắt lại\./, "and the new one is its own line");
  assert.match(rendered, /🔧 `search_notes` → tìm "họp"/);
  assert.match(rendered, /✅ `search_notes` · 3 kết quả/);
});

test("a failed tool result renders as a failure, carrying the error text", () => {
  const timeline = new ThinkingTimeline();
  timeline.toolStart("create_note", { title: "Ghi chú mới" });
  timeline.toolResult("create_note", { success: false, error: "permission denied" });

  const rendered = timeline.render();
  assert.match(rendered, /❌ `create_note`/);
  assert.match(rendered, /permission denied/);
});

test("the render only ever grows at the end — never rewrites what a sealed message already shows", async () => {
  // The correctness property behind every bound in this file.
  // `_syncMultiMessage` seals a chunk once a later one exists and never
  // edits it again, so a render that trimmed from the front or compacted
  // a long thought's middle would leave that sealed message showing text
  // no longer in the block.
  const timeline = new ThinkingTimeline();
  const renders = [];
  for (let i = 0; i < 300; i++) {
    timeline.reasoning(`Đoạn suy nghĩ số ${i} với khá nhiều chữ để tổng độ dài lớn dần. `);
    if (i % 40 === 0) {
      timeline.toolStart("search_notes", { query: `truy vấn ${i}` });
      timeline.toolResult("search_notes", { result: { notes: [] }, success: true });
    }
    renders.push(timeline.render());
  }

  for (let i = 1; i < renders.length; i++) {
    assert.ok(
      renders[i].startsWith(renders[i - 1]) || renders[i - 1].endsWith("…"),
      `render ${i} must extend render ${i - 1}, not rewrite it`
    );
  }
});

test("the block stops growing at its budget instead of pushing the answer off the channel", async () => {
  const timeline = new ThinkingTimeline();
  for (let i = 0; i < 400; i++) {
    timeline.reasoning(`Đoạn suy nghĩ số ${i} với khá nhiều chữ để tổng độ dài lớn dần. `);
  }

  const rendered = timeline.render();
  assert.ok(rendered.length <= 6000, `got ${rendered.length} chars`);
  assert.match(rendered, /Đoạn suy nghĩ số 0 /, "the budget is spent from the start of the thinking, in order");
  assert.match(rendered, /…$/, "and says it was cut");
});

test("clear() empties the timeline — the web hides its timeline the moment the turn stops loading", () => {
  const timeline = new ThinkingTimeline();
  timeline.reasoning("đang nghĩ");
  timeline.clear();

  assert.equal(timeline.isEmpty(), true);
  assert.equal(timeline.render(), "");
});

test("tool descriptions and summaries read as sentences, matching the web's wording", () => {
  assert.equal(toolSemanticDescription("search_notes", { query: "báo cáo" }), 'tìm "báo cáo"');
  assert.equal(toolSemanticDescription("create_note", { content: "# Tiêu đề\nnội dung" }), 'note mới "Tiêu đề"');
  assert.equal(toolSemanticDescription("unknown_tool", { query: "x" }), "", "an unknown tool says nothing rather than guessing");

  assert.equal(toolResultSummary("list_notes", { notes: [1, 2] }, true), "2 kết quả");
  assert.equal(toolResultSummary("create_note", { version: 3, id: "abcdefgh12" }, true), "v3 • abcdefgh");
  assert.match(toolResultSummary("search_notes", { error: "boom" }, false), /^✗ boom/);
});

test("the finished render swaps the header instead of freezing mid-sentence — a block kept after the turn must not claim it is still thinking", () => {
  // Mirrors the web's toggle label going from "Thinking" to "Thoughts"
  // once `msg.loading` clears.
  const timeline = new ThinkingTimeline();
  timeline.reasoning("Đang cân nhắc.");

  assert.match(timeline.render(), /Đang suy nghĩ/);
  assert.match(timeline.render({ done: true }), /Đã suy nghĩ/);
  assert.ok(!timeline.render({ done: true }).includes("Đang suy nghĩ"));
});
