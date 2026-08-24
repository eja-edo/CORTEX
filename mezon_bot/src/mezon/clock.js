"use strict";

/**
 * Wall-clock rendering, in the timezone the user actually lives in.
 *
 * Every timestamp Cortex returns is a real instant (`TIMESTAMPTZ`,
 * serialised as UTC), and the rest of this bot's renderers print the ISO
 * string's own digits (`planCard.formatWhen`) — which is right for a
 * *date* the backend already treats as day-granular, and wrong for a
 * *time*: a 14:00 session in Ho Chi Minh City arrives as `07:00Z` and
 * would be offered as "07:00", an hour nobody scheduled anything at.
 *
 * The zone is the same convention the backend adopted for text it renders
 * itself (`Settings.DISPLAY_TIMEZONE`), read from the same environment
 * variable so the two services cannot drift apart by configuration. It is
 * **not** a per-user preference — none exists in the schema yet — so this
 * is a shared default with a known limitation, not a claim about where
 * anyone is.
 *
 * Only the controls that carry a time of day use this today (the
 * occurrence picker). Migrating the other renderers is deliberately not
 * bundled in: they print dates, where the offset cannot change the digits
 * that matter.
 */

const DEFAULT_TIMEZONE = "Asia/Ho_Chi_Minh";

// Sunday-first, matching `Date.getUTCDay()`'s own indexing so the lookup
// needs no arithmetic. "CN" then T2…T7 is how a Vietnamese calendar names
// its columns.
const WEEKDAYS = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];

/** The instant's Y/M/D/H/M *in `timezone`*, or null if it isn't a date.
 *
 *  Built from `Intl.DateTimeFormat.formatToParts` rather than by adding an
 *  offset: an offset that is correct today is wrong the moment a zone
 *  observes DST, and picking zones that don't is not something a config
 *  file can promise. */
function zoned(value, timezone = DEFAULT_TIMEZONE) {
  const date = value instanceof Date ? value : new Date(String(value));
  if (Number.isNaN(date.getTime())) return null;

  let parts;
  try {
    parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: timezone,
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(date);
  } catch {
    // An unknown zone name is a configuration mistake, not a reason to
    // stop answering — fall back to the default rather than throwing in
    // the middle of rendering a card.
    parts = new Intl.DateTimeFormat("en-GB", {
      timeZone: DEFAULT_TIMEZONE,
      weekday: "short",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(date);
  }

  const at = (type) => parts.find((p) => p.type === type)?.value ?? "";
  // `hour12: false` still renders midnight as "24" in some ICU versions.
  const hour = at("hour") === "24" ? "00" : at("hour");
  return {
    year: at("year"),
    month: at("month"),
    day: at("day"),
    hour,
    minute: at("minute"),
    // `weekday: "short"` gives English ("Mon"); the index is what we want,
    // and `Date` cannot give it per-zone, so it is derived from the date
    // parts instead — a UTC date built from them has the right weekday.
    weekday:
      WEEKDAYS[
        new Date(`${at("year")}-${at("month")}-${at("day")}T00:00:00Z`).getUTCDay()
      ] ?? "",
  };
}

/** "T2 25/08 · 14:00" — the label the occurrence picker shows. */
function formatLocal(value, timezone = DEFAULT_TIMEZONE) {
  const z = zoned(value, timezone);
  if (!z) return null;
  return `${z.weekday} ${z.day}/${z.month} · ${z.hour}:${z.minute}`;
}

/** `YYYY-MM-DD` for an instant, as seen in `timezone`. */
function isoDate(value, timezone = DEFAULT_TIMEZONE) {
  const z = zoned(value, timezone);
  if (!z) return null;
  return `${z.year}-${z.month}-${z.day}`;
}

/**
 * `YYYY-MM-DD` for "tomorrow", where tomorrow is decided by the user's
 * clock and not by UTC's.
 *
 * At 23:30 in Ho Chi Minh City it is already the next day in Vietnam and
 * still today in UTC. Deriving this from `new Date()` directly would make
 * "dời sang mai" mean "dời sang hôm nay" for anyone acting late at night —
 * which is exactly when someone clears a nudge off their phone.
 */
function tomorrowIsoDate(timezone = DEFAULT_TIMEZONE, now = new Date()) {
  const today = isoDate(now, timezone);
  if (!today) return null;
  const next = new Date(`${today}T00:00:00Z`);
  next.setUTCDate(next.getUTCDate() + 1);
  return next.toISOString().slice(0, 10);
}

module.exports = { DEFAULT_TIMEZONE, zoned, formatLocal, isoDate, tomorrowIsoDate };
