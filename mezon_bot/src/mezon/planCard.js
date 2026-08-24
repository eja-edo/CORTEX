"use strict";

/**
 * `plan_proposal` as a preview card with Đồng ý / Bỏ qua.
 *
 * The stream event carries only `proposal_id` and `item_count` — the
 * items themselves live in the DB behind `GET /api/plan-proposals/{id}`,
 * which is why showing a preview here is a fetch and not a render of
 * something already in hand. That indirection is deliberate on the
 * backend's side: a proposal outlives the stream that announced it, so
 * approving one an hour later still works.
 *
 * Nothing is created until a button is pressed. `propose_plan` writes a
 * pending row and stops; `POST /approve` is what turns items into real
 * tasks and events. So this card is the entire decision point on this
 * surface — which is also why it renders enough of each item to *be* a
 * decision (when, how urgent, how long) rather than a title list that
 * looks the same whether the model understood the request or not.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");

// A preview is for deciding, not for reading in full; past this many
// items the card stops being scannable and the count carries the rest.
// The web has a scrollable pane and needs no such limit.
const MAX_ITEMS_SHOWN = 12;

const PRIORITY_ICON = { urgent: "🔴", high: "🟠", medium: "🟡", low: "⚪" };

/**
 * `2026-08-21T09:00:00+07:00` → `21/08 09:00`, read straight off the
 * string.
 *
 * Not via `Date`: parsing then formatting would re-express the instant in
 * *the bot process's* timezone, so a 09:00 meeting scheduled by a user in
 * Hanoi would render as 02:00 on a UTC server. The backend already sends
 * the offset the user meant; the only safe thing to do with it is not to
 * convert it.
 */
function formatWhen(value) {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/.exec(value.trim());
  if (!match) return null;
  const [, , month, day, hour, minute] = match;
  return hour ? `${day}/${month} ${hour}:${minute}` : `${day}/${month}`;
}

/** The one-line "what would be created" for an item. */
function itemLine(item) {
  const parts = [];
  if (item.type === "event") {
    const start = formatWhen(item.start_time);
    const end = formatWhen(item.end_time);
    if (start && end) {
      // Same-day events show the end as a bare time — "21/08 09:00 →
      // 10:30" reads as one block, "21/08 09:00 → 21/08 10:30" reads as
      // two separate things.
      const sameDay = start.slice(0, 5) === end.slice(0, 5);
      parts.push(`🕒 ${start} → ${sameDay && end.length > 5 ? end.slice(6) : end}`);
    } else if (start) {
      parts.push(`🕒 ${start}`);
    }
    if (item.location) parts.push(`📍 ${item.location}`);
    if (item.recurrence?.freq) parts.push(`🔁 ${String(item.recurrence.freq).toLowerCase()}`);
  } else {
    const due = formatWhen(item.due_date);
    if (due) parts.push(`📅 ${due}`);
    if (item.priority) parts.push(`${PRIORITY_ICON[item.priority] ?? "•"} ${item.priority}`);
  }
  if (item.description) parts.push(String(item.description).split("\n")[0].slice(0, 80));
  // A zero-width space, not "": an embed field with an empty value is
  // dropped by the client, taking the item's title with it.
  return parts.join(" · ") || "​";
}

function renderPlanProposal(proposal, { proposalId }) {
  const items = Array.isArray(proposal?.items) ? proposal.items : [];
  const tasks = items.filter((i) => i.type !== "event").length;
  const events = items.length - tasks;

  const summary = [tasks ? `${tasks} việc` : null, events ? `${events} lịch` : null]
    .filter(Boolean)
    .join(" + ");

  const form = new FormBuilder("📋 Cortex đề xuất một kế hoạch");
  form.description(
    `${summary || "Không có mục nào"} — chưa có gì được tạo. Bấm Tạo tất cả để thực hiện.`
  );

  for (const item of items.slice(0, MAX_ITEMS_SHOWN)) {
    form.field(`${item.type === "event" ? "📆" : "✅"} ${item.title}`, itemLine(item));
  }
  if (items.length > MAX_ITEMS_SHOWN) {
    form.field("…", `và ${items.length - MAX_ITEMS_SHOWN} mục nữa`);
  }

  form.button(actionId("plan_approve", proposalId), "✅ Tạo tất cả", STYLE.SUCCESS);
  form.button(actionId("plan_reject", proposalId), "✋ Bỏ qua", STYLE.SECONDARY);
  return form.build();
}

/**
 * What the card becomes after Đồng ý. Approval is best-effort per item
 * (`approve_proposal`'s docstring), so a partial result is a normal
 * outcome and the failures are named — "tạo 4/5" without saying which one
 * missed would send the user to the web app to find out.
 */
function renderPlanApproved(result) {
  const created = result?.created_count ?? 0;
  const failed = result?.failed_count ?? 0;
  const fields = (result?.results ?? [])
    .filter((r) => r.outcome !== "created")
    .slice(0, MAX_ITEMS_SHOWN)
    .map((r) => ({ name: `❌ ${r.key}`, value: r.error ? String(r.error).slice(0, 200) : "không tạo được" }));

  return notice(
    failed ? "📋 Đã tạo một phần" : "📋 Đã tạo xong",
    failed ? `Tạo được ${created}, lỗi ${failed}.` : `Đã tạo ${created} mục.`,
    { fields, color: failed ? "#f0a020" : "#2ea043" }
  );
}

/**
 * The card for a proposal that is no longer pending.
 *
 * This exists because of an asymmetry worth stating: the backend refuses
 * to approve a `rejected` or `expired` proposal, but **approving an
 * already-approved one is allowed** and would create every item a second
 * time (`approve_proposal` guards only those two statuses). On the web
 * the card is gone once decided; on Mezon a message with live buttons
 * outlives the bot process that sent it, so a click after a restart is a
 * duplicate-creation bug waiting to happen. The router checks status
 * before deciding, and this is what the user sees when it has already
 * been settled.
 */
function renderPlanAlreadyDecided(status) {
  const said = {
    approved: "Kế hoạch này đã được tạo trước đó rồi.",
    rejected: "Kế hoạch này đã bị bỏ qua trước đó.",
    expired: "Đề xuất này đã hết hạn.",
  };
  return notice("📋 Đã xử lý", said[status] ?? `Đề xuất đang ở trạng thái \`${status}\`.`, {
    color: "#8b949e",
  });
}

function renderPlanRejected() {
  return notice("📋 Đã bỏ qua kế hoạch", "Không có gì được tạo.", { color: "#8b949e" });
}

module.exports = {
  renderPlanProposal,
  renderPlanApproved,
  renderPlanRejected,
  renderPlanAlreadyDecided,
  itemLine,
  formatWhen,
  MAX_ITEMS_SHOWN,
};
