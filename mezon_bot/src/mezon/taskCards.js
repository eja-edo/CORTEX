"use strict";

/**
 * `*tasks` and `*task` — the two writes worth having in chat.
 *
 * `*tasks` is a list **and** an action in one card, deliberately. The
 * alternative was `*tasks` to look and `*done <id>` to act, which on this
 * surface means asking a person to retype a UUID they can see on screen.
 * A radio of open tasks plus one button is the same two steps without
 * that.
 *
 * Neither card decides anything: `POST /tasks/{id}/complete` runs the
 * real transition (`TASK_STATUS_TRANSITIONS` rejects illegal ones), and
 * `POST /tasks` takes the same body the web sends.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");
const { formatDay } = require("./agendaCard");

const TASK_FIELD_ID = "task";
const TITLE_FIELD_ID = "title";
const DUE_FIELD_ID = "due";
const PRIORITY_FIELD_ID = "priority";

// A radio the length of someone's whole backlog is not a control, it's a
// scroll. The newest/soonest are what a chat surface can usefully act on.
const MAX_PICKABLE = 10;

const PRIORITY_ICON = { urgent: "🔴", high: "🟠", medium: "🟡", low: "⚪" };
const PRIORITIES = ["urgent", "high", "medium", "low"];

/** One task as a radio option: title first, then whatever context the
 *  task actually has, since a list of bare titles is hard to pick from. */
function taskOption(task) {
  const bits = [];
  const due = formatDay(task.due_date);
  if (due) bits.push(`📅 ${due}`);
  if (task.priority) bits.push(`${PRIORITY_ICON[task.priority] ?? "•"} ${task.priority}`);
  return {
    label: task.title.slice(0, 100),
    value: String(task.id),
    description: bits.join(" · ") || undefined,
  };
}

function renderTaskList(tasks, formId, { heading }) {
  const form = new FormBuilder("✅ Việc đang mở");
  const shown = tasks.slice(0, MAX_PICKABLE);
  form.description(
    tasks.length > shown.length
      ? `${heading} — hiện ${shown.length}/${tasks.length} việc.`
      : heading
  );

  form.radio(TASK_FIELD_ID, "Chọn việc để đánh dấu xong", shown.map(taskOption), {
    multiple: false,
  });
  form.button(actionId("task_complete", formId), "Đánh dấu xong", STYLE.SUCCESS);
  return form.build();
}

/** Nothing open — a real answer, not an empty control. */
function renderNoTasks() {
  return notice("✅ Không có việc nào đang mở", "Chưa có gì phải làm cả.", { color: "#2ea043" });
}

function renderTaskCompleted(task) {
  return notice("✅ Đã xong", `**${task.title}**`, { color: "#2ea043" });
}

/** The other half of acting on a nudge. Prints the new deadline rather
 *  than just "đã dời": "tomorrow" is only unambiguous while you are
 *  reading the message it was sent in. */
function renderTaskSnoozed(task, dueDate) {
  const day = formatDay(dueDate);
  return notice("⏰ Đã dời sang mai", `**${task.title}**${day ? ` — hạn mới ${day}` : ""}`, {
    color: "#f0a020",
  });
}

/**
 * The create form. `title` is pre-filled from the command's arguments
 * (`*task viết đề cương`) — and pre-filling is not just convenience here:
 * an untouched field is absent from the submission entirely (§VIII bis
 * 8b), so a `defaultValue` is the only way a field the user leaves alone
 * still arrives.
 */
function renderTaskForm(title, formId) {
  const form = new FormBuilder("📝 Việc mới");
  form.description("Chỉ tiêu đề là bắt buộc.");
  form.textInput(TITLE_FIELD_ID, "Tiêu đề", { defaultValue: title ?? "" });
  form.datePicker(DUE_FIELD_ID, "Hạn (không bắt buộc)");
  form.radio(
    PRIORITY_FIELD_ID,
    "Ưu tiên (không bắt buộc)",
    PRIORITIES.map((p) => ({ label: `${PRIORITY_ICON[p]} ${p}`, value: p })),
    { multiple: false }
  );
  form.button(actionId("task_create", formId), "Tạo", STYLE.PRIMARY);
  return form.build();
}

function renderTaskCreated(task) {
  const fields = [];
  const due = formatDay(task.due_date);
  if (due) fields.push({ name: "Hạn", value: due, inline: true });
  if (task.priority) fields.push({ name: "Ưu tiên", value: task.priority, inline: true });
  return notice("📝 Đã tạo việc", `**${task.title}**`, { fields, color: "#2ea043" });
}

module.exports = {
  renderTaskList,
  renderNoTasks,
  renderTaskCompleted,
  renderTaskSnoozed,
  renderTaskForm,
  renderTaskCreated,
  taskOption,
  TASK_FIELD_ID,
  TITLE_FIELD_ID,
  DUE_FIELD_ID,
  PRIORITY_FIELD_ID,
  MAX_PICKABLE,
  PRIORITIES,
};
