"use strict";

/**
 * Tests for acting on a notification from inside the DM that carried it,
 * and for the occurrence question that stands in front of some of those
 * actions.
 *
 * Two properties are worth stating, because both are easy to break in a
 * way that still looks like it works:
 *
 * 1. **A notification's buttons carry everything they need.** A nudge sits
 *    in a chat list for days and is clicked after restarts, deploys and
 *    scrollback. Anything held in process memory would be gone; the tests
 *    below therefore act on a *fresh router* that has never seen the
 *    message it is answering.
 *
 * 2. **The bot never picks an occurrence.** A checklist task on a
 *    recurring event has one row and many sessions, and the API refuses to
 *    guess which one a write means (422). The bot asks the user instead —
 *    it does not helpfully assume "today".
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MessageRouter } = require("../src/router");
const { CommandRegistry } = require("../src/commands/registry");
const { tasksCommand } = require("../src/commands/tasks");
const { notification } = require("../src/mezon/embed");
const { parseActionId } = require("../src/mezon/actions");

function makeRouter(cortex) {
  const sent = [];
  const edits = [];
  let nextId = 1;
  const gateway = {
    sendToChannel: async (channelId, content) => {
      const id = `msg-${nextId++}`;
      sent.push({ channelId, content, id });
      return { id };
    },
    editMessage: async (channelId, messageId, content) => {
      edits.push({ channelId, messageId, content });
      return { id: messageId };
    },
  };
  const registry = new CommandRegistry({ prefix: "*" }).register(tasksCommand);
  const router = new MessageRouter({
    gateway,
    registry,
    cortex,
    prefix: "*",
    timezone: "Asia/Ho_Chi_Minh",
  });
  return { router, sent, edits };
}

const linked = { resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }) };
const message = (text) => ({ text, senderId: "mezon-u1", channelId: "ch-1", scope: "dm", mode: 4 });

function buttonEvent(buttonId, values) {
  return {
    button_id: buttonId,
    message_id: "card-msg",
    channel_id: "ch-1",
    user_id: "mezon-u1",
    sender_id: "bot-id",
    extra_data: values === undefined ? "" : JSON.stringify(values),
  };
}

const buttonsOf = (content) => content.components?.[0]?.components ?? [];
const submitIdOf = (m) => m.content.components[0].components[0].id;
const dump = (m) => JSON.stringify(m.content);

// ── What a delivered notification looks like ─────────────────────────────

test("a task nudge offers the two answers to it, plus the way to stop being asked", () => {
  const built = notification({
    title: "Quá hạn: Viết đề cương",
    body: "Trễ 3 ngày · hạn 21/08",
    attention_level: "recommend",
    reason_key: "task.overdue",
    payload: { task_id: "task-1", overdue_days: 3 },
  });

  const ids = buttonsOf(built).map((b) => b.id);
  assert.deepEqual(ids.map((id) => parseActionId(id)), [
    { kind: "notif_task_done", targetId: "task-1" },
    { kind: "notif_task_snooze", targetId: "task-1" },
    { kind: "notif_mute", targetId: "task.overdue" },
  ]);
});

test("a digest has no single subject, so it gets no task buttons — only the off switch", () => {
  const built = notification({
    title: "Đầu ngày — 3 việc",
    body: "3 việc đến hạn hôm nay",
    attention_level: "inform",
    reason_key: "day.plan",
    payload: {},
  });

  assert.deepEqual(
    buttonsOf(built).map((b) => parseActionId(b.id).kind),
    ["notif_mute"]
  );
});

test("a notification with nothing to act on shows no empty button row", () => {
  const built = notification({ title: "Xin chào", body: "", attention_level: "inform" });
  assert.equal(built.components, undefined);
});

test("the reason key stays printed as well as bound to a button — it is the string *mute takes", () => {
  const built = notification({
    title: "Quá hạn: X",
    attention_level: "ask",
    reason_key: "task.at_risk",
    payload: { task_id: "t1" },
  });
  assert.match(JSON.stringify(built), /task\.at_risk/);
});

// ── Acting on one ────────────────────────────────────────────────────────

test("✅ Xong completes the task the button names, on a router that never saw the notification", async () => {
  const completed = [];
  const cortex = {
    ...linked,
    getTask: async (id) => ({ id, title: "Viết đề cương", related_event_id: null }),
    completeTask: async (id, userId, occurrence) => {
      completed.push({ id, userId, occurrence });
      return { id, title: "Viết đề cương" };
    },
  };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("nd:task-1"));

  assert.deepEqual(completed, [{ id: "task-1", userId: "cortex-u1", occurrence: null }]);
  assert.match(JSON.stringify(edits[0].content), /Đã xong/);
  // The card is replaced, so the buttons are gone and the nudge cannot be
  // answered twice.
  assert.equal(edits[0].content.components, undefined);
});

test("⏰ Dời sang mai moves the deadline instead of closing the task", async () => {
  const updates = [];
  const cortex = {
    ...linked,
    getTask: async (id) => ({ id, title: "Viết đề cương", related_event_id: null }),
    updateTask: async (id, body, userId, occurrence) => {
      updates.push({ id, body, occurrence });
      return { id, title: "Viết đề cương" };
    },
    completeTask: async () => { throw new Error("must not complete when snoozing"); },
  };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("ns:task-1"));

  assert.equal(updates.length, 1);
  assert.match(updates[0].body.due_date, /^\d{4}-\d{2}-\d{2}T00:00:00Z$/);
  assert.match(JSON.stringify(edits[0].content), /Đã dời/);
});

test("🔕 turns off exactly the one reason, not notifications as a whole", async () => {
  const muted = [];
  const cortex = {
    ...linked,
    setReasonEnabled: async (key, enabled, userId) => { muted.push({ key, enabled, userId }); },
  };
  const { router, edits } = makeRouter(cortex);

  await router.handleButton(buttonEvent("nm:task.overdue"));

  assert.deepEqual(muted, [{ key: "task.overdue", enabled: false, userId: "cortex-u1" }]);
  assert.match(JSON.stringify(edits[0].content), /task\.overdue/);
});

test("a task that has since been deleted is reported, and nothing is written", async () => {
  let wrote = false;
  const cortex = {
    ...linked,
    getTask: async () => null,
    completeTask: async () => { wrote = true; },
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleButton(buttonEvent("nd:task-gone"));

  assert.equal(wrote, false);
  assert.match(dump(sent[0]), /Không tìm thấy/);
});

// ── The occurrence question ──────────────────────────────────────────────

const recurringTask = { id: "task-1", title: "10 từ mới", related_event_id: "event-1" };

function recurringCortex(extra = {}) {
  return {
    ...linked,
    getTask: async () => recurringTask,
    listTasks: async () => [recurringTask],
    getSchedule: async () => ({ id: "event-1", title: "Luyện từ vựng", is_recurring: true }),
    listScheduleInstances: async () => ({
      instances: [
        { start_time: "2026-08-24T00:30:00Z" },
        { start_time: "2026-08-25T00:30:00Z" },
      ],
    }),
    ...extra,
  };
}

test("completing a recurring event's checklist item asks which session instead of sending a 422", async () => {
  let completed = 0;
  const cortex = recurringCortex({ completeTask: async () => { completed += 1; } });
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  const listFormId = parseActionId(submitIdOf(sent[0])).targetId;
  await router.handleButton(buttonEvent(`tc:${listFormId}`, { task: "task-1" }));

  assert.equal(completed, 0, "no write may happen before the user says which session");
  assert.match(dump(sent[1]), /Buổi nào/);
  // Both answers are offered: one session, or every session.
  assert.deepEqual(
    buttonsOf(sent[1].content).map((b) => parseActionId(b.id).kind),
    ["occurrence_this", "occurrence_all"]
  );
});

test("the session picker shows local times, not the UTC digits they arrive as", async () => {
  const cortex = recurringCortex();
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  await router.handleButton(
    buttonEvent(`tc:${parseActionId(submitIdOf(sent[0])).targetId}`, { task: "task-1" })
  );

  // The option's *value* stays the raw instant — it is what the write is
  // keyed on — while its label is what the user reads.
  const labels = sent[1].content.embed[0].fields[0].inputs.component.map((o) => o.label);
  assert.deepEqual(labels, ["T2 24/08 · 07:30", "T3 25/08 · 07:30"]);
});

test('"Chỉ buổi này" writes the chosen session and nothing else', async () => {
  const completed = [];
  const cortex = recurringCortex({
    completeTask: async (id, userId, occurrence) => { completed.push({ id, occurrence }); return { id, title: "10 từ mới" }; },
  });
  const { router, sent, edits } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  await router.handleButton(
    buttonEvent(`tc:${parseActionId(submitIdOf(sent[0])).targetId}`, { task: "task-1" })
  );
  const pickerId = parseActionId(buttonsOf(sent[1].content)[0].id).targetId;

  await router.handleButton(buttonEvent(`oc:${pickerId}`, { occurrence: "2026-08-25T00:30:00Z" }));

  assert.deepEqual(completed, [
    { id: "task-1", occurrence: { startTime: "2026-08-25T00:30:00Z", scope: "this_only" } },
  ]);
  assert.match(JSON.stringify(edits[edits.length - 1].content), /10 từ mới/);
});

test('"Tất cả các buổi" says so on the write, so the template is what changes', async () => {
  const completed = [];
  const cortex = recurringCortex({
    completeTask: async (id, userId, occurrence) => { completed.push(occurrence); return { id, title: "10 từ mới" }; },
  });
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  await router.handleButton(
    buttonEvent(`tc:${parseActionId(submitIdOf(sent[0])).targetId}`, { task: "task-1" })
  );
  const pickerId = parseActionId(buttonsOf(sent[1].content)[1].id).targetId;

  await router.handleButton(buttonEvent(`oa:${pickerId}`, {}));

  assert.equal(completed[0].scope, "all");
});

test("snoozing a recurring checklist item asks the same question before moving any deadline", async () => {
  let updated = 0;
  const cortex = recurringCortex({ updateTask: async () => { updated += 1; return {}; } });
  const { router, sent } = makeRouter(cortex);

  await router.handleButton(buttonEvent("ns:task-1"));

  assert.equal(updated, 0);
  assert.match(dump(sent[0]), /Buổi nào/);
  assert.match(dump(sent[0]), /dời sang mai/);
});

test("an event with no sessions in range still offers the one write that needs no session", async () => {
  const completed = [];
  const cortex = recurringCortex({
    listScheduleInstances: async () => ({ instances: [] }),
    completeTask: async (id, userId, occurrence) => { completed.push(occurrence); return { id, title: "10 từ mới" }; },
  });
  const { router, sent } = makeRouter(cortex);

  await router.handleButton(buttonEvent("nd:task-1"));

  const offered = buttonsOf(sent[0].content).map((b) => parseActionId(b.id));
  assert.deepEqual(offered.map((a) => a.kind), ["occurrence_all"]);

  // And it has to actually work: an empty picker that still shows a button
  // must not answer the click with "chưa chọn buổi nào".
  await router.handleButton(buttonEvent(`oa:${offered[0].targetId}`, {}));
  assert.equal(completed.length, 1);
  assert.equal(completed[0].scope, "all");
});

test("pressing Chỉ buổi này without choosing a session asks again rather than picking one", async () => {
  let completed = 0;
  const cortex = recurringCortex({
    listScheduleInstances: async () => ({ instances: [] }),
    completeTask: async () => { completed += 1; },
  });
  const { router, sent } = makeRouter(cortex);

  await router.handleButton(buttonEvent("nd:task-1"));
  // The picker offered no radio, so this is the id of the only button on
  // it; asking for `this_only` against it is what a stale or hand-made
  // click looks like.
  const formId = parseActionId(buttonsOf(sent[0].content)[0].id).targetId;

  await router.handleButton(buttonEvent(`oc:${formId}`, {}));

  assert.equal(completed, 0);
  assert.match(dump(sent[1]), /Chưa chọn buổi nào/);
});
