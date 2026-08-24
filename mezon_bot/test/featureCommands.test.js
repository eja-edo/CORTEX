"use strict";

/**
 * Tests for the Tier 1/2 feature commands — `*today`, `*next`, `*tasks`,
 * `*new`, `*mute`, `*inbox`.
 *
 * The property every one of them has to keep is the thin-bot rule: the
 * bot picks an endpoint and renders the answer, and never computes one.
 * So these assert *which call happened with what*, and that what came
 * back reaches the user unedited — not that the bot produced some
 * particular judgement of its own.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MessageRouter } = require("../src/router");
const { CommandRegistry } = require("../src/commands/registry");
const { todayCommand, nextCommand } = require("../src/commands/agenda");
const { tasksCommand } = require("../src/commands/tasks");
const { newTaskCommand } = require("../src/commands/newTask");
const { muteCommand } = require("../src/commands/mute");
const { inboxCommand } = require("../src/commands/inbox");
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
  const registry = new CommandRegistry({ prefix: "*" })
    .register(todayCommand)
    .register(nextCommand)
    .register(tasksCommand)
    .register(newTaskCommand)
    .register(muteCommand)
    .register(inboxCommand);
  const router = new MessageRouter({ gateway, registry, cortex, prefix: "*" });
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
    extra_data: JSON.stringify(values),
  };
}

const submitIdOf = (m) => m.content.components[0].components[0].id;
const dump = (m) => JSON.stringify(m.content);

// ── *today / *next ───────────────────────────────────────────────────────

test("*today prints the server's impact sentence verbatim — it is the product's output, not a label to summarise", async () => {
  const impact = "Quá hạn 3 ngày. Càng để lâu càng khó bắt đầu lại.";
  const cortex = {
    ...linked,
    getToday: async () => ({
      state: "has_actions",
      status_line: "3 việc cần chú ý",
      now_actions: [{ task_id: "t1", title: "Viết đề cương", reason: { key: "task.overdue", impact }, priority: "high" }],
    }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*today"));

  assert.match(dump(sent[0]), new RegExp(impact.slice(0, 20)));
  assert.equal(sent[0].content.embed[0].description, "3 việc cần chú ý");
});

test("*today renders the served state, never inferring one from an empty list", async () => {
  // TodayResponse.state exists precisely so a client cannot fall through
  // to a blank table; "all_clear" and "nothing_urgent" are real answers.
  const cortex = { ...linked, getToday: async () => ({ state: "all_clear", now_actions: [] }) };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*today"));

  assert.match(dump(sent[0]), /Xong hết rồi/);
});

test("*today shows suggestions as things you could start, not as urgency", async () => {
  const cortex = {
    ...linked,
    getToday: async () => ({
      state: "nothing_urgent",
      now_actions: [],
      suggestions: [{ task_id: "t2", title: "Đọc tài liệu", reason: { key: "task.idle", impact: "Chưa đụng tới 2 tuần." } }],
    }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*today"));

  assert.match(dump(sent[0]), /Không có gì gấp/);
  assert.match(dump(sent[0]), /Đọc tài liệu/);
});

test("*next carries the at-risk list, which is the whole reason it is a separate endpoint", async () => {
  const cortex = {
    ...linked,
    getNextAction: async () => ({
      state: "has_actions",
      now_actions: [],
      at_risk: [{ task_id: "t3", title: "Nộp báo cáo", risk_score: 0.8, impact: "Hạn còn 1 ngày, còn 3 việc con chưa xong" }],
    }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*next"));

  assert.match(dump(sent[0]), /Đang có rủi ro/);
  assert.match(dump(sent[0]), /còn 3 việc con chưa xong/);
});

test("a task Cortex only guessed at is labelled a guess, kept apart from real work", async () => {
  const cortex = {
    ...linked,
    getToday: async () => ({
      state: "has_actions",
      now_actions: [{ task_id: "t1", title: "Việc thật", reason: { key: "task.overdue", impact: "Quá hạn." } }],
      needs_confirmation: [{ task_id: "t9", title: "Gọi cho anh Nam" }],
    }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*today"));

  assert.match(dump(sent[0]), /Cortex đoán, chưa xác nhận/);
});

// ── *tasks ───────────────────────────────────────────────────────────────

test("*tasks asks for open work only — pending_confirm is a proposal, not a task", async () => {
  let query = null;
  const cortex = {
    ...linked,
    listTasks: async (userId, params) => { query = { userId, params }; return []; },
  };
  const { router } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));

  assert.equal(query.userId, "cortex-u1");
  assert.equal(query.params.status, "todo");
  assert.equal(query.params.due_before, undefined);
});

test("*tasks today narrows with due_before rather than filtering in the bot", async () => {
  let params = null;
  const cortex = { ...linked, listTasks: async (_u, p) => { params = p; return []; } };
  const { router } = makeRouter(cortex);

  await router.handleMessage(message("*tasks today"));

  assert.match(params.due_before, /^\d{4}-\d{2}-\d{2}$/);
});

test("no open work is a real answer, not an empty control to pick from", async () => {
  const cortex = { ...linked, listTasks: async () => [] };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));

  assert.equal(sent[0].content.components, undefined);
  assert.match(dump(sent[0]), /Không có việc nào đang mở/);
});

test("picking a task and pressing the button completes it against the backend", async () => {
  const completed = [];
  const cortex = {
    ...linked,
    listTasks: async () => [{ id: "task-1", title: "Viết đề cương", priority: "high" }],
    completeTask: async (id, userId) => { completed.push({ id, userId }); return {}; },
  };
  const { router, sent, edits } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`tc:${formId}`, { task: "task-1" }));

  assert.deepEqual(completed, [{ id: "task-1", userId: "cortex-u1" }]);
  assert.match(JSON.stringify(edits[edits.length - 1].content), /Viết đề cương/);
});

test("pressing complete with nothing selected does not guess a task", async () => {
  let called = false;
  const cortex = {
    ...linked,
    listTasks: async () => [{ id: "task-1", title: "Việc" }],
    completeTask: async () => { called = true; },
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*tasks"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`tc:${formId}`, {}));

  assert.equal(called, false);
  assert.match(sent[sent.length - 1].content.t, /Chưa chọn việc/);
});

// ── *new ─────────────────────────────────────────────────────────────────

test("*new pre-fills the title from the command line — an untouched field never arrives at all", async () => {
  // §VIII bis 8b: a field the user doesn't touch is absent from the
  // submission, so a defaultValue is the only way it survives.
  const { router, sent } = makeRouter(linked);

  await router.handleMessage(message("*new viết đề cương"));

  const titleField = sent[0].content.embed[0].fields[0];
  assert.equal(titleField.inputs.component.defaultValue, "viết đề cương");
});

test("creating a task sends the picked date as a day, since ranking is day-granular", async () => {
  const created = [];
  const cortex = {
    ...linked,
    createTask: async (body, userId) => { created.push({ body, userId }); return { title: body.title, due_date: body.due_date }; },
  };
  const { router, sent, edits } = makeRouter(cortex);

  await router.handleMessage(message("*new viết đề cương"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(
    buttonEvent(`tn:${formId}`, { title: "Viết đề cương", due: "2026-08-22", priority: "high" })
  );

  assert.deepEqual(created, [
    { body: { title: "Viết đề cương", due_date: "2026-08-22T00:00:00Z", priority: "high" }, userId: "cortex-u1" },
  ]);
  assert.match(JSON.stringify(edits[edits.length - 1].content), /Đã tạo việc/);
});

test("an impossible date from the platform's own picker is dropped, not sent on", async () => {
  // The probe recorded "34343-12-22" reaching the bot intact — the client
  // validates nothing.
  const created = [];
  const cortex = { ...linked, createTask: async (body) => { created.push(body); return { title: body.title }; } };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*new họp"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`tn:${formId}`, { title: "Họp", due: "34343-12-22" }));

  assert.deepEqual(created, [{ title: "Họp" }], "no due_date at all, rather than a task due in the year 34343");
});

test("a task with no title is refused before it reaches the backend", async () => {
  let called = false;
  const cortex = { ...linked, createTask: async () => { called = true; } };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*new"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`tn:${formId}`, { due: "2026-08-22" }));

  assert.equal(called, false);
  assert.match(sent[sent.length - 1].content.t, /cần có tiêu đề/);
});

// ── *mute ────────────────────────────────────────────────────────────────

test("*mute <reason_key> turns it off directly — the key is already printed on every notification", async () => {
  const calls = [];
  const cortex = {
    ...linked,
    listReasonPreferences: async () => [{ reason_key: "task.overdue", description: "Việc quá hạn", enabled: true }],
    setReasonEnabled: async (key, enabled, userId) => { calls.push({ key, enabled, userId }); return {}; },
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*mute task.overdue"));

  assert.deepEqual(calls, [{ key: "task.overdue", enabled: false, userId: "cortex-u1" }]);
  assert.match(dump(sent[0]), /Đã tắt/);
});

test("*mute with an unknown key says so instead of turning nothing off silently", async () => {
  let called = false;
  const cortex = {
    ...linked,
    listReasonPreferences: async () => [{ reason_key: "task.overdue", enabled: true }],
    setReasonEnabled: async () => { called = true; },
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*mute khong.ton.tai"));

  assert.equal(called, false);
  assert.match(sent[0].content.t, /Không có loại nhắc/);
});

test("the mute picker offers only what is currently on — one tap must not mean the opposite of the last", async () => {
  const cortex = {
    ...linked,
    listReasonPreferences: async () => [
      { reason_key: "task.overdue", enabled: true, effective_level: "recommend" },
      { reason_key: "day.review", enabled: false, effective_level: "inform" },
    ],
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*mute"));

  const options = sent[0].content.embed[0].fields[0].inputs.component;
  assert.deepEqual(options.map((o) => o.value), ["task.overdue"]);
});

test("submitting the mute picker turns the chosen reason off", async () => {
  const calls = [];
  const cortex = {
    ...linked,
    listReasonPreferences: async () => [{ reason_key: "task.overdue", enabled: true, description: "Việc quá hạn" }],
    setReasonEnabled: async (key, enabled) => { calls.push({ key, enabled }); return {}; },
  };
  const { router, sent, edits } = makeRouter(cortex);

  await router.handleMessage(message("*mute"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`mu:${formId}`, { reason: "task.overdue" }));

  assert.deepEqual(calls, [{ key: "task.overdue", enabled: false }]);
  assert.match(JSON.stringify(edits[edits.length - 1].content), /task\.overdue/);
});

// ── *inbox ───────────────────────────────────────────────────────────────

test("*inbox puts unread first and marks them, since the list is ordered by recency", async () => {
  const cortex = {
    ...linked,
    listNotifications: async () => ({
      items: [
        { id: "n1", title: "Đã đọc", body: "x", read_at: "2026-08-19T00:00:00Z", attention_level: "inform" },
        { id: "n2", title: "Chưa đọc", body: "y", read_at: null, attention_level: "recommend" },
      ],
      total: 2,
    }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*inbox"));

  const names = sent[0].content.embed[0].fields.map((f) => f.name);
  assert.match(names[0], /Chưa đọc/);
  assert.match(names[0], /🔵/);
  assert.ok(!names[1].includes("🔵"));
});

test("an all-read inbox offers no clear button", async () => {
  const cortex = {
    ...linked,
    listNotifications: async () => ({ items: [{ id: "n1", title: "Cũ", read_at: "2026-08-19T00:00:00Z" }], total: 1 }),
  };
  const { router, sent } = makeRouter(cortex);

  await router.handleMessage(message("*inbox"));

  assert.equal(sent[0].content.components, undefined);
});

test("clearing the inbox marks everything read on the backend", async () => {
  let cleared = null;
  const cortex = {
    ...linked,
    listNotifications: async () => ({ items: [{ id: "n1", title: "Mới", read_at: null }], total: 1 }),
    markAllNotificationsRead: async (userId) => { cleared = userId; return {}; },
  };
  const { router, sent, edits } = makeRouter(cortex);

  await router.handleMessage(message("*inbox"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`ir:${formId}`, {}));

  assert.equal(cleared, "cortex-u1");
  assert.match(JSON.stringify(edits[edits.length - 1].content), /Đã đọc hết/);
});

// ── shared ───────────────────────────────────────────────────────────────

test("every feature command needs a linked account — they all act on a Cortex user", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: false }),
    getToday: async () => { throw new Error("must not be called"); },
    listTasks: async () => { throw new Error("must not be called"); },
    listReasonPreferences: async () => { throw new Error("must not be called"); },
    listNotifications: async () => { throw new Error("must not be called"); },
  };

  for (const text of ["*today", "*next", "*tasks", "*new x", "*mute", "*inbox"]) {
    const { router, sent } = makeRouter(cortex);
    await assert.doesNotReject(router.handleMessage(message(text)));
    assert.match(sent[0].content.t, /chưa liên kết/i, `${text} must refuse`);
  }
});
