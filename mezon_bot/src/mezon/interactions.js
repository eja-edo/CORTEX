"use strict";

/**
 * Reading what a user did with a form.
 *
 * Every rule here is an observation from the M0 probe against the live
 * gateway (docs/mezon-bot-plan.md §VIII bis), not an assumption about how
 * a chat platform "should" behave. Three of them are counter-intuitive
 * enough that getting any one wrong produces a bug that looks like
 * something else entirely:
 *
 * 1. **`extra_data` is not always JSON.** A SELECT fires
 *    `message_button_clicked` the instant a user picks an option, with
 *    `button_id` set to the select's own id and `extra_data` set to the
 *    bare value — `"a"`, not `{"p_select":"a"}`. A blind `JSON.parse`
 *    throws on every dropdown interaction.
 *
 * 2. **`user_id` is the actor; `sender_id` is the bot.** `sender_id`
 *    identifies whoever authored the message carrying the button, which
 *    for our forms is always us. Attributing an action to `sender_id`
 *    credits the bot for everything the user does.
 *
 * 3. **Untouched fields are absent, not empty.** The web client only
 *    records a field once it is interacted with, so a blank input is
 *    missing from the object rather than present as `""`. Absent
 *    therefore means "unchanged", never "cleared".
 */

/** Values a form field can carry. Numbers arrive as strings — `"1.5"`, not
 *  1.5 — and dates as `YYYY-MM-DD`; neither is coerced here, because
 *  coercion belongs where the field's meaning is known. */
function parseExtraData(raw) {
  if (typeof raw !== "string" || raw.length === 0) {
    return { kind: "empty", values: {}, raw };
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // Rule 1: a bare value from a select-change event.
    return { kind: "scalar", values: {}, scalar: raw, raw };
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    // Valid JSON but not the form object — a quoted string, a number.
    return { kind: "scalar", values: {}, scalar: parsed, raw };
  }

  return { kind: "form", values: parsed, raw };
}

/**
 * Normalised view of a button-click event.
 *
 * `isFormSubmission` is what callers should branch on rather than
 * re-deriving it: the distinction between "user submitted a form" and
 * "user moved a dropdown" is not visible in the event type, only in the
 * shape of what came with it.
 */
function parseButtonEvent(event) {
  const extra = parseExtraData(event?.extra_data);
  return {
    buttonId: event?.button_id ?? null,
    messageId: event?.message_id ?? null,
    channelId: event?.channel_id ?? null,
    // Rule 2. Named `actorId` so no call site has to remember which of the
    // two id fields is the human.
    actorId: event?.user_id ?? null,
    messageAuthorId: event?.sender_id ?? null,
    extra,
    isFormSubmission: extra.kind === "form",
  };
}

/** Rule 3: absent means "unchanged". Callers that need "the user cleared
 *  this" must model it as an explicit value, never as absence. */
function hasField(values, id) {
  return Object.prototype.hasOwnProperty.call(values ?? {}, id);
}

function getText(values, id, fallback = null) {
  const value = values?.[id];
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.length ? String(value[0]) : fallback;
  return value === undefined || value === null ? fallback : String(value);
}

/** Multi-select radios return `string[]`; single ones return `string`.
 *  Both are normalised to an array so callers stop caring which is which —
 *  a distinction driven by how the *options* were configured, not by
 *  anything the caller controls. */
function getList(values, id) {
  const value = values?.[id];
  if (value === undefined || value === null) return [];
  return Array.isArray(value) ? value.map(String) : [String(value)];
}

/** Numeric inputs arrive as strings and the platform does not validate
 *  them. Returns `null` for anything non-finite rather than `NaN`, so a
 *  bad value cannot silently propagate as a number. */
function getNumber(values, id) {
  const raw = getText(values, id);
  if (raw === null || raw.trim() === "") return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * A `YYYY-MM-DD` date, or null.
 *
 * The probe recorded `"34343-12-22"` from a real datepicker: the client
 * enforces nothing, so a five-digit year reaches the bot intact. The range
 * check is not defensive programming for its own sake — it is the only
 * thing standing between a typo and a task due in the year 34343.
 */
function getDate(values, id) {
  const raw = getText(values, id);
  if (!raw) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(raw.trim());
  if (!match) return null;

  const [, y, m, d] = match;
  const year = Number(y);
  const month = Number(m);
  const day = Number(d);
  if (year < 1970 || year > 2100 || month < 1 || month > 12 || day < 1 || day > 31) {
    return null;
  }

  // Round-trip through Date to reject the days that pass the range check
  // but do not exist — 2026-02-31 among them.
  const asDate = new Date(Date.UTC(year, month - 1, day));
  if (
    asDate.getUTCFullYear() !== year ||
    asDate.getUTCMonth() !== month - 1 ||
    asDate.getUTCDate() !== day
  ) {
    return null;
  }
  return `${y}-${m}-${d}`;
}

module.exports = {
  parseExtraData,
  parseButtonEvent,
  hasField,
  getText,
  getList,
  getNumber,
  getDate,
};
