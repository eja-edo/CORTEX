"use strict";

/**
 * Tests for the room-end → project pick → summary cards (`roomWatch.js`'s
 * rendering half). Asserts against `InteractiveBuilder`'s real output shape
 * (`{title, description, fields: [{name, value, inputs}], ...}` — see
 * `mezon-sdk`'s `InteractiveMessage.js`), the same way `embed.test.js` does
 * for `fieldsToEmbed`.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const {
  renderProjectPicker,
  renderProjectPickConfirmed,
  renderMeetingSummary,
  renderTasksCreatedFromSummary,
  PROJECT_FIELD_ID,
  NO_PROJECT_VALUE,
} = require("../src/mezon/roomWatchCards");

function radioField(content) {
  return content.embed[0].fields.find((f) => f.inputs?.id === PROJECT_FIELD_ID);
}

const PROJECTS = [
  { id: "p1", name: "Dự án A" },
  { id: "p2", name: "Dự án B" },
];

test("renderProjectPicker lists every project plus a no-project option, and names the room", () => {
  const content = renderProjectPicker(PROJECTS, "Họp tuần", "form-1");

  assert.match(content.embed[0].description, /Họp tuần/);
  const field = radioField(content);
  assert.deepEqual(
    field.inputs.component.map(({ label, value }) => ({ label, value })),
    [
      { label: "Dự án A", value: "p1" },
      { label: "Dự án B", value: "p2" },
      { label: "Không gắn dự án nào", value: NO_PROJECT_VALUE },
    ]
  );
});

test("renderProjectPicker's submit button targets the given form id", () => {
  const content = renderProjectPicker(PROJECTS, "Họp tuần", "form-1");
  const button = content.components[0].components[0];
  assert.equal(button.id, "pj:form-1");
  assert.equal(button.component.label, "Xác nhận");
});

test("renderProjectPicker with no projects still offers the no-project option", () => {
  const content = renderProjectPicker([], "Họp tuần", "form-1");
  const field = radioField(content);
  assert.deepEqual(
    field.inputs.component.map(({ label, value }) => ({ label, value })),
    [{ label: "Không gắn dự án nào", value: NO_PROJECT_VALUE }]
  );
});

test("renderProjectPickConfirmed names both the room and the chosen project, with no buttons", () => {
  const content = renderProjectPickConfirmed("Họp tuần", "Dự án A");
  assert.match(content.embed[0].description, /Họp tuần/);
  assert.match(content.embed[0].description, /Dự án A/);
  assert.equal(content.components, undefined);
});

test("renderMeetingSummary shows the summary text and details, names the room in the title", () => {
  const content = renderMeetingSummary("Họp tuần", {
    summary: "Đã bàn về tiến độ Q1.",
    action_items: {},
    detail: ["Chốt dùng PostgreSQL"],
  });

  assert.match(content.embed[0].title, /Họp tuần/);
  assert.equal(content.embed[0].description, "Đã bàn về tiến độ Q1.");
  const detailField = content.embed[0].fields.find((f) => f.name === "Chi tiết");
  assert.equal(detailField.value, "• Chốt dùng PostgreSQL");
});

test("renderMeetingSummary with no detail items adds no detail field", () => {
  const content = renderMeetingSummary("Họp tuần", { summary: "Tóm tắt.", action_items: {}, detail: [] });
  assert.equal(content.embed[0].fields.find((f) => f.name === "Chi tiết"), undefined);
});

test("renderTasksCreatedFromSummary lists every created task title", () => {
  const content = renderTasksCreatedFromSummary(["Việc 1", "Việc 2"]);
  assert.equal(content.embed[0].description, "• Việc 1\n• Việc 2");
});

test("renderTasksCreatedFromSummary says so, rather than an empty list, when there was nothing to create", () => {
  const content = renderTasksCreatedFromSummary([]);
  assert.match(content.embed[0].title, /Không có việc/);
});
