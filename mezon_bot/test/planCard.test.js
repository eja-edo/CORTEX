"use strict";

/**
 * Tests for the `plan_proposal` preview card and its outcomes.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  renderPlanProposal,
  renderPlanApproved,
  renderPlanRejected,
  renderPlanAlreadyDecided,
  itemLine,
  formatWhen,
} = require("../src/mezon/planCard");
const { parseActionId } = require("../src/mezon/actions");

const PROPOSAL = {
  status: "pending",
  items: [
    { key: "t1", type: "task", title: "Viết đề cương", due_date: "2026-08-22T17:00:00+07:00", priority: "high" },
    {
      key: "e1",
      type: "event",
      title: "Họp review",
      start_time: "2026-08-21T09:00:00+07:00",
      end_time: "2026-08-21T10:30:00+07:00",
      location: "P.301",
    },
  ],
};

test("a time is read off the string, never re-expressed in the bot's timezone", () => {
  // Parsing through `Date` would render a 09:00 Hanoi meeting as 02:00 on
  // a UTC server — the backend already sends the offset the user meant,
  // and the only safe thing to do with it is not convert it.
  assert.equal(formatWhen("2026-08-21T09:00:00+07:00"), "21/08 09:00");
  assert.equal(formatWhen("2026-08-21"), "21/08");
  assert.equal(formatWhen("không phải ngày"), null);
  assert.equal(formatWhen(undefined), null);
});

test("an item line says enough to decide on: when, and how urgent or how long", () => {
  assert.equal(itemLine(PROPOSAL.items[0]), "📅 22/08 17:00 · 🟠 high");
  assert.equal(itemLine(PROPOSAL.items[1]), "🕒 21/08 09:00 → 10:30 · 📍 P.301", "same-day end shows as a bare time");
});

test("an item with nothing to add still renders a non-empty value — an empty one is dropped by the client, title and all", () => {
  const line = itemLine({ key: "t9", type: "task", title: "Chỉ có tiêu đề" });
  assert.notEqual(line, "");
});

test("the card counts what would be created and says nothing has been yet", () => {
  const content = renderPlanProposal(PROPOSAL, { proposalId: "p-1" });
  const embed = content.embed[0];

  assert.match(embed.description, /1 việc \+ 1 lịch/);
  assert.match(embed.description, /chưa có gì được tạo/i);
  assert.equal(embed.fields.length, 2);
});

test("both decisions are buttons the router can route on, carrying the proposal id", () => {
  const buttons = renderPlanProposal(PROPOSAL, { proposalId: "p-1" }).components[0].components;
  assert.deepEqual(parseActionId(buttons[0].id), { kind: "plan_approve", targetId: "p-1" });
  assert.deepEqual(parseActionId(buttons[1].id), { kind: "plan_reject", targetId: "p-1" });
});

test("a long plan is trimmed with the remainder counted, not rendered in full", () => {
  const many = { items: Array.from({ length: 20 }, (_, i) => ({ key: `t${i}`, type: "task", title: `Việc ${i}` })) };
  const fields = renderPlanProposal(many, { proposalId: "p-2" }).embed[0].fields;

  assert.ok(fields.length <= 13, `12 items plus one "…" row, got ${fields.length}`);
  assert.match(fields[fields.length - 1].value, /8 mục nữa/);
});

test("a partial approval names the items that failed", () => {
  // Approval is best-effort per item, so partial is a normal outcome —
  // "tạo 1/2" without saying which one missed sends the user to the web
  // app to find out.
  const content = renderPlanApproved({
    created_count: 1,
    failed_count: 1,
    results: [
      { key: "t1", outcome: "created" },
      { key: "e1", outcome: "failed", error: "trùng lịch" },
    ],
  });

  assert.match(content.embed[0].title, /một phần/);
  assert.equal(content.embed[0].fields.length, 1);
  assert.match(content.embed[0].fields[0].value, /trùng lịch/);
});

test("a clean approval says only what was created", () => {
  const content = renderPlanApproved({ created_count: 3, failed_count: 0, results: [] });
  assert.match(content.embed[0].description, /3 mục/);
  assert.equal(content.embed[0].fields?.length ?? 0, 0);
});

test("every outcome card drops the buttons — a decision must not be makeable twice from one message", () => {
  for (const content of [
    renderPlanApproved({ created_count: 1, failed_count: 0, results: [] }),
    renderPlanRejected(),
    renderPlanAlreadyDecided("approved"),
  ]) {
    assert.equal(content.components, undefined);
  }
});

test("an already-decided proposal explains which way it went", () => {
  assert.match(renderPlanAlreadyDecided("approved").embed[0].description, /đã được tạo/);
  assert.match(renderPlanAlreadyDecided("rejected").embed[0].description, /bỏ qua/);
  assert.match(renderPlanAlreadyDecided("expired").embed[0].description, /hết hạn/);
  assert.match(renderPlanAlreadyDecided("gì đó lạ").embed[0].description, /gì đó lạ/, "an unknown status is shown, not swallowed");
});
