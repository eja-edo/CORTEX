"use strict";

/**
 * Tests for `renderAgenda` — the shared card behind `*today` and `*next`.
 *
 * Focus is the `schedules_today` addition (backend 2.7 follow-up:
 * `TodayService` now knows about calendar events, not just tasks) and the
 * `schedule_only` state it introduced. Before this, a day with an event but
 * no open task rendered an essentially empty card — `schedule_only` isn't
 * in `EMPTY_STATE`, so the old renderer fell through the "nowActions +
 * suggestions" branches with both empty and produced a title with no
 * fields at all.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const { renderAgenda, formatEventTime, scheduleLine } = require("../src/mezon/agendaCard");

function fieldNamed(content, name) {
  return content.embed[0].fields.find((f) => f.name === name);
}

test("formatEventTime keeps only the time half of a full datetime", () => {
  assert.equal(formatEventTime("2026-09-02T19:00:00Z"), "19:00");
  assert.equal(formatEventTime(null), null);
});

test("scheduleLine includes the location when there is one, omits it when there isn't", () => {
  assert.equal(
    scheduleLine({ title: "Nghe - Nói / Shadowing", start_time: "2026-09-02T19:00:00Z", location: "Phòng 101" }),
    "• 19:00 Nghe - Nói / Shadowing — Phòng 101"
  );
  assert.equal(
    scheduleLine({ title: "Họp nhóm", start_time: "2026-09-02T09:00:00Z", location: null }),
    "• 09:00 Họp nhóm"
  );
});

test("schedule_only renders the schedules field instead of falling through to an empty card", () => {
  const content = renderAgenda(
    {
      state: "schedule_only",
      now_actions: [],
      suggestions: [],
      needs_confirmation: [],
      schedules_today: [
        { schedule_id: "s1", title: "Nghe - Nói / Shadowing", start_time: "2026-09-02T19:00:00Z", location: null },
      ],
    },
    { title: "📅 Hôm nay" }
  );

  const field = fieldNamed(content, "📅 Lịch hôm nay");
  assert.ok(field, "expected a 'Lịch hôm nay' field, got none");
  assert.match(field.value, /19:00 Nghe - Nói \/ Shadowing/);
});

test("all_clear with no schedule is still the old canned notice — unaffected by the addition", () => {
  const content = renderAgenda(
    { state: "all_clear", now_actions: [], suggestions: [], needs_confirmation: [], schedules_today: [] },
    { title: "📅 Hôm nay" }
  );

  assert.match(content.embed[0].title, /Xong hết rồi/);
  assert.equal(content.embed[0].fields.length, 0);
});

test("has_actions with a schedule today shows both the ranked action and the schedule", () => {
  const content = renderAgenda(
    {
      state: "has_actions",
      now_actions: [
        { task_id: "t1", title: "Nộp báo cáo", reason: { key: "task.overdue", impact: "Quá hạn 1 ngày." } },
      ],
      suggestions: [],
      needs_confirmation: [],
      schedules_today: [
        { schedule_id: "s1", title: "Họp nhóm", start_time: "2026-09-02T09:00:00Z", location: null },
      ],
    },
    { title: "📅 Hôm nay" }
  );

  assert.ok(fieldNamed(content, "1. Nộp báo cáo"));
  assert.ok(fieldNamed(content, "📅 Lịch hôm nay"));
});

test("no schedule today means no schedules field at all, not an empty one", () => {
  const content = renderAgenda(
    {
      state: "has_actions",
      now_actions: [{ task_id: "t1", title: "Nộp báo cáo", reason: { key: "task.overdue", impact: "Quá hạn 1 ngày." } }],
      suggestions: [],
      needs_confirmation: [],
      schedules_today: [],
    },
    { title: "📅 Hôm nay" }
  );

  assert.equal(fieldNamed(content, "📅 Lịch hôm nay"), undefined);
});

test("*next's response (no schedules_today field at all) renders exactly as before — the field is optional", () => {
  const content = renderAgenda(
    {
      state: "has_actions",
      now_actions: [{ task_id: "t1", title: "Nộp báo cáo", reason: { key: "task.overdue", impact: "Quá hạn 1 ngày." } }],
      suggestions: [],
      needs_confirmation: [],
      at_risk: [{ title: "Việc rủi ro", impact: "Rủi ro đang tăng." }],
      // no schedules_today key — NextActionResponse doesn't carry one
    },
    { title: "➡️ Làm gì tiếp theo" }
  );

  assert.equal(fieldNamed(content, "📅 Lịch hôm nay"), undefined);
  assert.ok(fieldNamed(content, "⚠️ Đang có rủi ro"));
});
