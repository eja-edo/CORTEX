"use strict";

/**
 * Cards for the room-end → project pick → summary flow (`roomWatch.js`).
 *
 * Three moments, three cards: the picker sent right after a room ends, what
 * it becomes once answered, and the summary + action-items confirmation
 * sent once orchestrator's `room_summary_done` arrives. The picker follows
 * `modelCard.js`'s shape — fetch a list, render it as a radio, resolve the
 * submitted value against the same list — because that is exactly what
 * picking a project is.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");

const PROJECT_FIELD_ID = "project";

// The radio's escape hatch: `TaskCreate.project_id` is optional on the wire
// and the backend already knows what to do with "no opinion" — fall back to
// the caller's personal project (`ProjectService.resolve_for_task`). This
// value is never sent to the backend itself; `roomWatch.js` reads it and
// omits `project_id` entirely.
const NO_PROJECT_VALUE = "__none__";

/**
 * `projects` is `[{id, name}]` from `cortex.listProjects`; `roomName` is
 * shown so the picker reads as "which meeting is this about" even for
 * someone in several rooms a day.
 */
function renderProjectPicker(projects, roomName, formId) {
  const form = new FormBuilder("🗂️ Chọn dự án cho cuộc họp");
  form.description(
    `Cuộc họp **${roomName}** đã kết thúc. Chọn dự án để nhận tóm tắt và việc cần làm khi tổng kết xong.`
  );

  const options = projects.map((project) => ({ label: project.name, value: project.id }));
  options.push({ label: "Không gắn dự án nào", value: NO_PROJECT_VALUE });

  form.radio(PROJECT_FIELD_ID, "Dự án", options, { multiple: false });
  form.button(actionId("project_pick", formId), "Xác nhận", STYLE.PRIMARY);
  return form.build();
}

/** What the picker becomes once answered — no buttons, so a second click
 *  on scrollback cannot register a second answer. */
function renderProjectPickConfirmed(roomName, projectLabel) {
  return notice(
    "🗂️ Đã ghi nhận",
    `Cuộc họp **${roomName}** → **${projectLabel}**. Sẽ gửi tóm tắt và tạo việc khi có tổng kết.`,
    { color: "#2ea043" }
  );
}

/**
 * The summary DM once `room_summary_done` arrives.
 *
 * `summaryData` is the `summary_data` object documented in
 * `docs/API_REFERENCE.md` §6 — `{summary, action_items, detail}`, or `{}`
 * while a failed LLM call is being retried. Callers check for
 * `action_items` before calling this (see `roomWatch.js`), so by the time
 * this renders, `summary`/`detail` are trusted to be present.
 */
function renderMeetingSummary(roomName, summaryData) {
  const form = new FormBuilder(`📋 Tóm tắt cuộc họp — ${roomName}`);
  if (summaryData.summary) form.description(summaryData.summary);
  if (summaryData.detail?.length) {
    form.field("Chi tiết", summaryData.detail.map((line) => `• ${line}`).join("\n"));
  }
  return form.build();
}

/** Confirms which action items became tasks — empty is a real answer too,
 *  not just a card that says nothing. */
function renderTasksCreatedFromSummary(items) {
  if (!items.length) {
    return notice("✅ Không có việc cần làm mới", "Cuộc họp không có mục nào cần tạo việc.", {
      color: "#2ea043",
    });
  }
  return notice(
    "✅ Đã tạo việc từ cuộc họp",
    items.map((title) => `• ${title}`).join("\n"),
    { color: "#2ea043" }
  );
}

module.exports = {
  renderProjectPicker,
  renderProjectPickConfirmed,
  renderMeetingSummary,
  renderTasksCreatedFromSummary,
  PROJECT_FIELD_ID,
  NO_PROJECT_VALUE,
};
