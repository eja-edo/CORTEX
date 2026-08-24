"use strict";

/**
 * `*mute` and `*inbox` — the notification surface managing itself.
 *
 * These two exist because of a specific asymmetry: this bot's reason for
 * existing is to interrupt people (R4), and until now the only way to
 * answer an interruption was to open the web app. "Thông báo DM gây
 * phiền" is listed as a live risk in the plan (§VII); a mute that takes
 * one message is the difference between a user turning off one reason and
 * a user blocking the bot.
 *
 * The reason list is fetched, never hard-coded — `GET /preferences/
 * reasons` returns every registered `reason_key` with its level and
 * on/off state, and that catalogue moves independently of this bot.
 * Every notification the bot sends already prints its `reason_key` in the
 * footer (see `embed.js`'s `notification`), so the string in front of the
 * user is exactly the one this list is keyed by.
 */

const { FormBuilder, STYLE, notice, LEVEL_STYLE } = require("./embed");
const { actionId } = require("./actions");

const REASON_FIELD_ID = "reason";
const MAX_REASONS = 12;
const MAX_NOTIFICATIONS = 8;

/**
 * The mute picker.
 *
 * Only *enabled* reasons are offered. Turning one back on is a
 * deliberately different act — `*mute` is a stop button, and mixing "off"
 * rows into the same radio would make one tap silently mean the opposite
 * of the last one. Re-enabling stays on the web's audit list, which shows
 * dismiss counts and effective levels this card has no room for.
 */
function renderMutePicker(reasons, formId) {
  const enabled = reasons.filter((r) => r.enabled !== false).slice(0, MAX_REASONS);
  if (enabled.length === 0) {
    return notice(
      "🔕 Đã tắt hết rồi",
      "Không còn loại nhắc nào đang bật. Bật lại trong Cortex → Settings.",
      { color: "#8b949e" }
    );
  }

  const form = new FormBuilder("🔕 Tắt một loại nhắc");
  form.description("Chọn loại nhắc bạn không muốn nhận nữa. Bật lại được trên web.");
  form.radio(
    REASON_FIELD_ID,
    "Loại nhắc",
    enabled.map((reason) => ({
      label: `${LEVEL_STYLE[reason.effective_level]?.icon ?? "•"} ${reason.reason_key}`,
      value: reason.reason_key,
      description: (reason.description ?? "").slice(0, 100) || undefined,
    })),
    { multiple: false }
  );
  form.button(actionId("mute_submit", formId), "Tắt", STYLE.DANGER);
  return form.build();
}

function renderMuted(reason) {
  return notice(
    "🔕 Đã tắt",
    `Sẽ không nhắc \`${reason.reason_key}\` nữa.` +
      (reason.description ? `\n\n_${reason.description}_` : ""),
    { fields: [{ name: "Bật lại", value: "Cortex → Settings → Loại nhắc" }], color: "#8b949e" }
  );
}

/**
 * The inbox.
 *
 * Unread first and marked as such, because the list is ordered by
 * recency, not by whether it still wants attention — a notification the
 * user already dealt with on the web should not look identical to one
 * they have never seen.
 */
function renderInbox(items, formId) {
  const unread = items.filter((n) => !n.read_at);
  if (items.length === 0) {
    return notice("📥 Hộp thư trống", "Chưa có thông báo nào.", { color: "#8b949e" });
  }

  const form = new FormBuilder("📥 Thông báo");
  form.description(unread.length ? `${unread.length} thông báo chưa đọc.` : "Đã đọc hết.");

  const ordered = [...unread, ...items.filter((n) => n.read_at)].slice(0, MAX_NOTIFICATIONS);
  for (const item of ordered) {
    const icon = LEVEL_STYLE[item.attention_level]?.icon ?? "•";
    const mark = item.read_at ? "" : "🔵 ";
    const body = (item.body ?? "").split("\n")[0].slice(0, 150);
    form.field(
      `${mark}${icon} ${item.title}`,
      [body, item.reason_key ? `\`${item.reason_key}\`` : null].filter(Boolean).join("\n") || "​"
    );
  }

  if (unread.length) {
    form.button(actionId("inbox_read_all", formId), "Đánh dấu đã đọc hết", STYLE.SECONDARY);
  }
  return form.build();
}

function renderInboxCleared(count) {
  return notice("📥 Đã đọc hết", count ? `Đã đánh dấu ${count} thông báo.` : "Không còn gì chưa đọc.", {
    color: "#8b949e",
  });
}

module.exports = {
  renderMutePicker,
  renderMuted,
  renderInbox,
  renderInboxCleared,
  REASON_FIELD_ID,
  MAX_REASONS,
  MAX_NOTIFICATIONS,
};
