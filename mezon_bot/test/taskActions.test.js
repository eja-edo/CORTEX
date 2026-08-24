"use strict";

/**
 * Tests for the occurrence rules around writing to a task, and for the
 * clock they depend on.
 *
 * The property being protected is a negative one: **the bot never invents
 * an occurrence.** A checklist task on a recurring event is one row shared
 * by every session, and the API answers 422 rather than guessing which one
 * a write means. Every test here exists because the cheap alternative —
 * "assume today's session" — would be indistinguishable from working, right
 * up until it silently ticked off the wrong day.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  INTENT,
  prepareTaskWrite,
  applyTaskWrite,
  listOccurrences,
} = require("../src/taskActions");
const { formatLocal, isoDate, tomorrowIsoDate } = require("../src/mezon/clock");

const NOW = new Date("2026-08-24T03:00:00Z"); // 10:00 in Asia/Ho_Chi_Minh

// ── prepareTaskWrite ─────────────────────────────────────────────────────

test("an ordinary task is written straight away — no event, nothing to ask", async () => {
  let scheduleFetches = 0;
  const cortex = {
    getSchedule: async () => { scheduleFetches += 1; return null; },
  };

  const prepared = await prepareTaskWrite({
    cortex,
    userId: "u1",
    taskId: "t1",
    task: { id: "t1", title: "Viết đề cương", related_event_id: null },
  });

  assert.equal(prepared.ready, true);
  assert.equal(scheduleFetches, 0);
});

test("a checklist task on a NON-recurring event still writes directly", async () => {
  const cortex = {
    getSchedule: async () => ({ id: "e1", title: "Họp kickoff", is_recurring: false }),
  };

  const prepared = await prepareTaskWrite({
    cortex,
    userId: "u1",
    taskId: "t1",
    task: { id: "t1", title: "Chuẩn bị slide", related_event_id: "e1" },
  });

  assert.equal(prepared.ready, true);
});

test("a checklist task on a recurring event stops and collects the sessions to choose from", async () => {
  const cortex = {
    getSchedule: async () => ({ id: "e1", title: "Luyện từ vựng", is_recurring: true }),
    listScheduleInstances: async () => ({
      instances: [
        { start_time: "2026-08-23T00:30:00Z" },
        { start_time: "2026-08-24T00:30:00Z" },
        { start_time: "2026-08-25T00:30:00Z" },
      ],
    }),
  };

  const prepared = await prepareTaskWrite({
    cortex,
    userId: "u1",
    taskId: "t1",
    task: { id: "t1", title: "10 từ mới", related_event_id: "e1" },
    now: NOW,
  });

  assert.equal(prepared.ready, false);
  assert.equal(prepared.event.title, "Luyện từ vựng");
  assert.equal(prepared.occurrences.length, 3);
});

test("the task is fetched when the caller only has an id — a notification button carries nothing else", async () => {
  const cortex = {
    getTask: async (id) => ({ id, title: "Từ một notification", related_event_id: null }),
  };

  const prepared = await prepareTaskWrite({ cortex, userId: "u1", taskId: "t9" });

  assert.equal(prepared.ready, true);
  assert.equal(prepared.task.title, "Từ một notification");
});

test("a task that no longer exists is reported, not written to", async () => {
  const cortex = { getTask: async () => null };
  const prepared = await prepareTaskWrite({ cortex, userId: "u1", taskId: "gone" });
  assert.equal(prepared.missing, true);
});

// ── listOccurrences ──────────────────────────────────────────────────────

test("sessions are chosen by nearness to now but listed in time order", async () => {
  const cortex = {
    listScheduleInstances: async () => ({
      instances: [
        { start_time: "2026-08-01T00:30:00Z" }, // far past
        { start_time: "2026-08-23T00:30:00Z" }, // yesterday
        { start_time: "2026-08-24T00:30:00Z" }, // today
        { start_time: "2026-08-25T00:30:00Z" },
        { start_time: "2026-08-26T00:30:00Z" },
        { start_time: "2026-09-20T00:30:00Z" }, // far future
      ],
    }),
  };

  const found = await listOccurrences({ cortex, userId: "u1", eventId: "e1", now: NOW, limit: 4 });

  assert.deepEqual(found, [
    "2026-08-23T00:30:00Z",
    "2026-08-24T00:30:00Z",
    "2026-08-25T00:30:00Z",
    "2026-08-26T00:30:00Z",
  ]);
});

test("an exception row is identified by original_start_time — the instant the API matches on", async () => {
  const cortex = {
    listScheduleInstances: async () => ({
      instances: [{ start_time: "2026-08-24T02:00:00Z", original_start_time: "2026-08-24T00:30:00Z" }],
    }),
  };

  const found = await listOccurrences({ cortex, userId: "u1", eventId: "e1", now: NOW });

  assert.deepEqual(found, ["2026-08-24T00:30:00Z"]);
});

test("an unreachable instances endpoint yields an empty list, not a thrown click", async () => {
  const cortex = {
    listScheduleInstances: async () => { throw new Error("500 boom"); },
  };
  assert.deepEqual(await listOccurrences({ cortex, userId: "u1", eventId: "e1", now: NOW }), []);
});

// ── applyTaskWrite ───────────────────────────────────────────────────────

test("completing passes the occurrence through untouched — the bot carries the answer, it does not form one", async () => {
  const calls = [];
  const cortex = {
    completeTask: async (taskId, userId, occurrence) => { calls.push({ taskId, userId, occurrence }); return { id: taskId }; },
  };

  await applyTaskWrite({
    cortex,
    userId: "u1",
    taskId: "t1",
    intent: INTENT.COMPLETE,
    occurrence: { startTime: "2026-08-24T00:30:00Z", scope: "this_only" },
  });

  assert.deepEqual(calls, [
    {
      taskId: "t1",
      userId: "u1",
      occurrence: { startTime: "2026-08-24T00:30:00Z", scope: "this_only" },
    },
  ]);
});

test("snoozing sets tomorrow at midnight UTC — the same convention *new already uses for a due date", async () => {
  const calls = [];
  const cortex = {
    updateTask: async (taskId, body, userId, occurrence) => { calls.push({ taskId, body, occurrence }); return { id: taskId }; },
  };

  const result = await applyTaskWrite({
    cortex,
    userId: "u1",
    taskId: "t1",
    intent: INTENT.SNOOZE,
    timezone: "Asia/Ho_Chi_Minh",
    now: NOW,
  });

  assert.equal(calls[0].body.due_date, "2026-08-25T00:00:00Z");
  assert.equal(result.dueDate, "2026-08-25");
});

// ── clock ────────────────────────────────────────────────────────────────

test('"tomorrow" is measured on the user\'s clock, not UTC\'s — a nudge cleared after midnight must not be dated yesterday', () => {
  // 17:30Z is 00:30 on the 25th in Asia/Ho_Chi_Minh while UTC still reads
  // the 24th. Taking the date off `new Date().toISOString()` — which is
  // what every other date in this bot does — would set "mai" to the 25th:
  // the day the user is already living in.
  const justAfterMidnightLocal = new Date("2026-08-24T17:30:00Z");

  assert.equal(isoDate(justAfterMidnightLocal, "Asia/Ho_Chi_Minh"), "2026-08-25");
  assert.equal(tomorrowIsoDate("Asia/Ho_Chi_Minh", justAfterMidnightLocal), "2026-08-26");
});

test("a session's time is shown in the user's zone, not as the UTC digits it arrives as", () => {
  // 00:30Z is the 07:30 morning session it was scheduled as.
  assert.equal(formatLocal("2026-08-24T00:30:00Z", "Asia/Ho_Chi_Minh"), "T2 24/08 · 07:30");
});

test("an unknown timezone falls back instead of throwing mid-render", () => {
  assert.equal(formatLocal("2026-08-24T00:30:00Z", "Mars/Olympus"), "T2 24/08 · 07:30");
});

test("a non-date is null rather than the string NaN", () => {
  assert.equal(formatLocal("không phải ngày", "Asia/Ho_Chi_Minh"), null);
  assert.equal(isoDate(undefined, "Asia/Ho_Chi_Minh"), null);
});
