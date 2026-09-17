"use strict";

/**
 * Tests for `RoomWatchService` — the business logic behind "room ended →
 * ask which project → summary ready → DM it and create today's tasks."
 * `gateway`/`cortex`/`orchestrator` are hand-written fakes (same style as
 * `router.test.js`); `pendingForms` is the real `PendingForms`, since its
 * own behaviour is already covered by `pendingForms.test.js` and this file
 * only needs it as a plain store.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const { RoomWatchService, participantIdentity } = require("../src/roomWatch");
const { PendingForms } = require("../src/mezon/pendingForms");
const { PROJECT_FIELD_ID } = require("../src/mezon/roomWatchCards");

function makeFakes({ links = {}, projects = [], room = null, summary = null } = {}) {
  const dms = []; // { mezonUserId, content }
  const createdTasks = []; // { body, userId }

  const gateway = {
    sendDirectMessage: async (mezonUserId, content) => {
      dms.push({ mezonUserId, content });
      return { id: `msg-${dms.length}` };
    },
  };

  const cortex = {
    resolveChannel: async (mezonUserId) => links[mezonUserId] ?? { linked: false },
    listProjects: async () => projects,
    createTask: async (body, userId) => {
      createdTasks.push({ body, userId });
      return { id: `task-${createdTasks.length}`, ...body };
    },
  };

  const orchestrator = {
    getRoomById: async () => room,
    getSummaryByRoomId: async () => summary,
    streamMetadata: () => {},
    stop: () => {},
  };

  return { gateway, cortex, orchestrator, dms, createdTasks };
}

function service(fakes, extra = {}) {
  return new RoomWatchService({
    gateway: fakes.gateway,
    cortex: fakes.cortex,
    orchestrator: fakes.orchestrator,
    pendingForms: new PendingForms(),
    ...extra,
  });
}

// ---------------------------------------------------------------------------
// participantIdentity
// ---------------------------------------------------------------------------

test("participantIdentity accepts a bare string or number", () => {
  assert.equal(participantIdentity("180123"), "180123");
  assert.equal(participantIdentity(180123), "180123");
});

test("participantIdentity reads participant_identity/identity/id off an object", () => {
  assert.equal(participantIdentity({ participant_identity: "a" }), "a");
  assert.equal(participantIdentity({ identity: "b" }), "b");
  assert.equal(participantIdentity({ id: "c" }), "c");
});

test("participantIdentity returns null for a shape it doesn't recognise", () => {
  assert.equal(participantIdentity({ username: "no id here" }), null);
  assert.equal(participantIdentity(null), null);
});

// ---------------------------------------------------------------------------
// handleRoomEnded
// ---------------------------------------------------------------------------

test("handleRoomEnded DMs a project picker to every linked participant, skips unlinked ones", async () => {
  const fakes = makeFakes({
    links: { u1: { linked: true, user_id: "cortex-1" }, u2: { linked: false } },
    projects: [{ id: "p1", name: "Dự án A" }],
    room: { id: "r1", participants: ["u1", "u2"] },
  });
  const svc = service(fakes);

  await svc.handleRoomEnded({ room_id: "r1", room_name: "Họp tuần" });

  assert.equal(fakes.dms.length, 1);
  assert.equal(fakes.dms[0].mezonUserId, "u1");
  const field = fakes.dms[0].content.embed[0].fields.find((f) => f.inputs?.id === PROJECT_FIELD_ID);
  assert.ok(field, "picker must carry the project radio field");
});

test("handleRoomEnded accepts object-shaped participant entries too", async () => {
  const fakes = makeFakes({
    links: { u1: { linked: true, user_id: "cortex-1" } },
    projects: [],
    room: { id: "r1", participants: [{ participant_identity: "u1" }] },
  });
  const svc = service(fakes);

  await svc.handleRoomEnded({ room_id: "r1", room_name: "Họp tuần" });

  assert.equal(fakes.dms.length, 1);
  assert.equal(fakes.dms[0].mezonUserId, "u1");
});

test("handleRoomEnded does nothing when the room has no id", async () => {
  const fakes = makeFakes();
  const svc = service(fakes);
  await svc.handleRoomEnded({ room_name: "no id" });
  assert.equal(fakes.dms.length, 0);
});

// ---------------------------------------------------------------------------
// recordProjectPick + handleSummaryDone
// ---------------------------------------------------------------------------

test("handleSummaryDone with no waiters for the room does nothing", async () => {
  const fakes = makeFakes({ summary: { summary_data: { summary: "x", action_items: {}, detail: [] } } });
  const svc = service(fakes);
  await svc.handleSummaryDone({ room_id: "r1", room_name: "Họp tuần" });
  assert.equal(fakes.dms.length, 0);
});

test("handleSummaryDone DMs the summary and creates tasks from the waiter's own + general items", async () => {
  const fakes = makeFakes({
    summary: {
      summary_data: {
        summary: "Đã bàn tiến độ.",
        action_items: {
          u1: ["Cập nhật timeline"],
          general: ["Lên lịch review"],
        },
        detail: [],
      },
    },
  });
  const svc = service(fakes);
  svc.recordProjectPick({ roomId: "r1", roomName: "Họp tuần", mezonUserId: "u1", cortexUserId: "cortex-1", projectId: "p1" });

  await svc.handleSummaryDone({ room_id: "r1", room_name: "Họp tuần" });

  // One DM with the summary, one DM confirming the created tasks.
  assert.equal(fakes.dms.length, 2);
  assert.equal(fakes.dms[0].content.embed[0].description, "Đã bàn tiến độ.");

  assert.equal(fakes.createdTasks.length, 2);
  const titles = fakes.createdTasks.map((t) => t.body.title).sort();
  assert.deepEqual(titles, ["Cập nhật timeline", "Lên lịch review"]);
  for (const task of fakes.createdTasks) {
    assert.equal(task.userId, "cortex-1");
    assert.equal(task.body.project_id, "p1");
    assert.match(task.body.due_date, /T00:00:00Z$/);
  }
});

test("handleSummaryDone omits project_id when the waiter picked no project", async () => {
  const fakes = makeFakes({
    summary: { summary_data: { summary: "x", action_items: { u1: ["Việc 1"] }, detail: [] } },
  });
  const svc = service(fakes);
  svc.recordProjectPick({ roomId: "r1", roomName: "Họp tuần", mezonUserId: "u1", cortexUserId: "cortex-1", projectId: null });

  await svc.handleSummaryDone({ room_id: "r1", room_name: "Họp tuần" });

  assert.equal(fakes.createdTasks.length, 1);
  assert.equal("project_id" in fakes.createdTasks[0].body, false);
});

test("handleSummaryDone keeps the waiter and DMs nothing when summary_data has no action_items yet", async () => {
  const fakes = makeFakes({ summary: { summary_data: {} } });
  const svc = service(fakes);
  svc.recordProjectPick({ roomId: "r1", roomName: "Họp tuần", mezonUserId: "u1", cortexUserId: "cortex-1", projectId: "p1" });

  await svc.handleSummaryDone({ room_id: "r1", room_name: "Họp tuần" });

  assert.equal(fakes.dms.length, 0);
  assert.equal(fakes.createdTasks.length, 0);
  assert.equal(svc.waiters.get("r1").length, 1, "the waiter must still be there for a later retry");
});

test("handleSummaryDone delivers separately to two waiters who picked different projects", async () => {
  const fakes = makeFakes({
    summary: {
      summary_data: {
        summary: "x",
        action_items: { u1: ["Việc của u1"], u2: ["Việc của u2"] },
        detail: [],
      },
    },
  });
  const svc = service(fakes);
  svc.recordProjectPick({ roomId: "r1", roomName: "Họp tuần", mezonUserId: "u1", cortexUserId: "c1", projectId: "p1" });
  svc.recordProjectPick({ roomId: "r1", roomName: "Họp tuần", mezonUserId: "u2", cortexUserId: "c2", projectId: "p2" });

  await svc.handleSummaryDone({ room_id: "r1", room_name: "Họp tuần" });

  assert.equal(fakes.createdTasks.length, 2);
  const byUser = Object.fromEntries(fakes.createdTasks.map((t) => [t.userId, t]));
  assert.equal(byUser.c1.body.project_id, "p1");
  assert.equal(byUser.c1.body.title, "Việc của u1");
  assert.equal(byUser.c2.body.project_id, "p2");
  assert.equal(byUser.c2.body.title, "Việc của u2");

  assert.equal(svc.waiters.has("r1"), false, "waiters for the room are consumed once delivered");
});
