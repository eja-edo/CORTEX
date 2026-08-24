"use strict";

/**
 * "Buổi nào?" — the card that stands between a click and a write on a
 * checklist task that belongs to a recurring event.
 *
 * The API requires an occurrence for these tasks and refuses to assume one
 * (see `taskActions.js`). This is where the user supplies it. Two buttons
 * rather than one, because the two answers are genuinely different actions
 * and a radio cannot express "and also, all of the others":
 *
 *   · **Chỉ buổi này** — writes the selected session only, leaving every
 *     other occurrence as it was. This is the common case: one habit
 *     ticked off for today.
 *   · **Tất cả các buổi** — writes the template every un-overridden
 *     occurrence reads. Rarer and heavier, so it is the secondary style
 *     and never the pre-selected one.
 *
 * When the event has no occurrences in the window we look at, the radio is
 * omitted entirely and only "Tất cả các buổi" remains — a picker with
 * nothing in it invites a click that cannot work.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");
const { formatLocal, DEFAULT_TIMEZONE } = require("./clock");

const OCCURRENCE_FIELD_ID = "occurrence";

const INTENT_WORDS = {
  complete: { verb: "đánh dấu xong", title: "✅ Buổi nào?" },
  snooze: { verb: "dời sang mai", title: "⏰ Buổi nào?" },
};

/** The label for one session. `formatLocal` renders it in the user's
 *  timezone — an occurrence is a time of day, and the raw ISO string is
 *  UTC (see `clock.js`). */
function occurrenceOption(startTime, timezone) {
  return {
    label: formatLocal(startTime, timezone) ?? startTime,
    value: startTime,
  };
}

function renderOccurrencePicker({ task, event, occurrences, formId, intent, timezone = DEFAULT_TIMEZONE }) {
  const words = INTENT_WORDS[intent] ?? INTENT_WORDS.complete;
  const form = new FormBuilder(words.title);
  form.description(
    `**${task.title}** là việc trong checklist của lịch lặp` +
      (event?.title ? ` **${event.title}**` : "") +
      `.\nChọn buổi cần ${words.verb}, hoặc áp dụng cho tất cả các buổi.`
  );

  if (occurrences.length) {
    form.radio(
      OCCURRENCE_FIELD_ID,
      "Buổi",
      occurrences.map((start) => occurrenceOption(start, timezone)),
      { multiple: false }
    );
    form.button(actionId("occurrence_this", formId), "Chỉ buổi này", STYLE.SUCCESS);
  } else {
    // Said out loud rather than left as an empty control: "no sessions in
    // the next month" is information about the event, not a bot failure.
    form.field("Buổi", "Không tìm thấy buổi nào trong khoảng ±1 tháng.");
  }

  form.button(actionId("occurrence_all", formId), "Tất cả các buổi", STYLE.SECONDARY);
  return form.build();
}

/** What the picker becomes once answered. Names the session so the card
 *  left in the scrollback still says what was done, to what, and when. */
function renderOccurrenceDone({ task, intent, scope, startTime, dueDate, timezone = DEFAULT_TIMEZONE }) {
  const when = scope === "all" ? "tất cả các buổi" : formatLocal(startTime, timezone) ?? "buổi đã chọn";
  if (intent === "snooze") {
    return notice("⏰ Đã dời", `**${task.title}** — ${when}, hạn mới ${dueDate ?? "ngày mai"}.`, {
      color: "#f0a020",
    });
  }
  return notice("✅ Đã xong", `**${task.title}** — ${when}.`, { color: "#2ea043" });
}

module.exports = {
  renderOccurrencePicker,
  renderOccurrenceDone,
  occurrenceOption,
  OCCURRENCE_FIELD_ID,
};
