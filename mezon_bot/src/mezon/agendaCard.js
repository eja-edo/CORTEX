"use strict";

/**
 * `*today` and `*next` — the read-only halves of the "Hôm nay" screen.
 *
 * Both endpoints return the same state machine (`onboarding` /
 * `nothing_urgent` / `all_clear` / `has_actions`) and the same action
 * shape, so they share a renderer. `state` is **served, not inferred** —
 * `TodayResponse.state`'s own docstring says the client must never fall
 * back to a blank table — so every branch below is driven by it, and an
 * empty list is never treated as "nothing to say".
 *
 * The `impact` sentence is printed verbatim. It is composed server-side
 * because it *is* the product's output ("Quá hạn 3 ngày, MVP còn 12 ngày
 * và còn 4 việc chưa xong"); a bot that summarised it into "high
 * priority" would throw away the one thing that makes the screen worth
 * looking at, and could show something untrue.
 */

const { FormBuilder, notice } = require("./embed");
const { formatWhen } = require("./planCard");

// Chat is a scrolling column: past this many the card stops being a
// glance and becomes a document. The lists themselves are already capped
// server-side (3.1's MAX_NOW_ACTIONS); this is the backstop.
const MAX_ROWS = 6;

const PRIORITY_ICON = { urgent: "🔴", high: "🟠", medium: "🟡", low: "⚪" };

/** A due date, without the time.
 *
 *  `today.py` compares `.date()` on both sides — "overdue"/"due today"
 *  are day-granular by design there ("a task due at 23:00 today is 'due
 *  today', not 'overdue in -9 hours'"). Printing 00:00 next to a due date
 *  would imply a precision the ranking does not use. */
function formatDay(value) {
  const formatted = formatWhen(value);
  return formatted ? formatted.slice(0, 5) : null;
}

/** "21/08 · 🟠 high" — whichever of the two the item actually has. */
function actionMeta(action) {
  const parts = [];
  const due = formatDay(action.due_date);
  if (due) parts.push(`📅 ${due}`);
  if (action.priority) parts.push(`${PRIORITY_ICON[action.priority] ?? "•"} ${action.priority}`);
  return parts.join(" · ");
}

function actionField(action, index) {
  const meta = actionMeta(action);
  // The reason is the point of the row; the metadata is context for it.
  const impact = action.reason?.impact ?? "";
  return {
    name: `${index + 1}. ${action.title}`,
    value: [impact, meta].filter(Boolean).join("\n") || "​",
  };
}

const EMPTY_STATE = {
  onboarding: {
    title: "👋 Chưa có gì để hiện",
    body: "Cortex chưa biết bạn đang làm gì. Thêm vài việc rồi quay lại đây.",
  },
  all_clear: {
    title: "✅ Xong hết rồi",
    body: "Không còn việc nào đang chờ. Nghỉ đi.",
  },
};

/**
 * @param {object} data  TodayResponse or NextActionResponse
 * @param {object} opts  `title` differs between the two commands; `atRisk`
 *                       is next-action-only (6.8/4.4).
 */
function renderAgenda(data, { title }) {
  const state = data?.state;
  const nowActions = data?.now_actions ?? [];
  const suggestions = data?.suggestions ?? [];
  const needsConfirmation = data?.needs_confirmation ?? [];
  const atRisk = data?.at_risk ?? [];

  const empty = EMPTY_STATE[state];
  if (empty && nowActions.length === 0 && suggestions.length === 0) {
    return notice(empty.title, empty.body, { color: "#2ea043" });
  }

  const form = new FormBuilder(title);
  if (data?.status_line) form.description(data.status_line);

  if (nowActions.length) {
    nowActions.slice(0, MAX_ROWS).forEach((a, i) => {
      const f = actionField(a, i);
      form.field(f.name, f.value);
    });
  }

  // `nothing_urgent` is a real answer, not an absence of one — the
  // suggestions are things the user *could* start, and saying so is what
  // stops them reading as invented urgency.
  if (!nowActions.length && suggestions.length) {
    form.field("Không có gì gấp", "Nếu muốn làm gì đó:");
    suggestions.slice(0, MAX_ROWS).forEach((a, i) => {
      const f = actionField(a, i);
      form.field(f.name, f.value);
    });
  }

  if (atRisk.length) {
    form.field(
      "⚠️ Đang có rủi ro",
      atRisk
        .slice(0, MAX_ROWS)
        .map((r) => `• **${r.title}** — ${r.impact}`)
        .join("\n")
    );
  }

  if (needsConfirmation.length) {
    // Deliberately last and deliberately labelled a guess: these are
    // tasks the extractor proposed, and presenting them next to real work
    // would pass an AI guess off as validated fact.
    form.field(
      "❓ Cortex đoán, chưa xác nhận",
      needsConfirmation
        .slice(0, MAX_ROWS)
        .map((t) => `• ${t.title}`)
        .join("\n")
    );
  }

  return form.build();
}

module.exports = { renderAgenda, actionMeta, formatDay, MAX_ROWS };
