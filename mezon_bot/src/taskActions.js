"use strict";

/**
 * The two writes chat can make to a task — finish it, push it to tomorrow
 * — and the one question that has to be answered first.
 *
 * ## Why this file exists
 *
 * A checklist task on a *recurring* event is one row shared by every
 * occurrence of that event (`Task.recurrence_id`, migration
 * `a1b2c3d4e5f6`). Completing it therefore has to say *which session*, and
 * the API enforces that: `POST /tasks/{id}/complete` and `PATCH
 * /tasks/{id}` answer **422** unless `occurrence_start_time` and
 * `edit_scope` are both present. Before this file, every button in the bot
 * called them bare, so ticking "10 từ mới" off a daily practice session
 * produced an error card.
 *
 * The tempting fix — have the bot assume "today's session" — is the one
 * thing this feature must not do. The backend refuses to guess on purpose;
 * a bot that guesses on its behalf just moves the wrong answer somewhere
 * with less information. So the flow is: ask Cortex whether the task needs
 * a scope, and if it does, ask the *user* which occurrence, then write.
 *
 * ## Shape
 *
 * `prepareTaskWrite` answers "can I write this now?" and `applyTaskWrite`
 * does the write. They are separate because between them sits a card and
 * a click — possibly minutes apart, possibly never.
 */

const { tomorrowIsoDate, DEFAULT_TIMEZONE } = require("./mezon/clock");

const INTENT = { COMPLETE: "complete", SNOOZE: "snooze" };

// How far around "now" to look for the sessions worth offering. Backwards
// as well as forwards because the nudge that prompts someone to act is
// usually about a session that has already been and gone ("quá hạn"), and
// a picker that only lists the future cannot express what they came to do.
const LOOK_BACK_DAYS = 7;
const LOOK_AHEAD_DAYS = 30;

// A radio the length of a month of daily sessions is a scroll, not a
// control. Five is enough to reach yesterday, today and the next few, and
// short enough to read on a phone.
const MAX_OCCURRENCES = 5;

function isoOffsetDays(from, days) {
  const at = new Date(from.getTime());
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString();
}

/** The instant an occurrence is identified by. `original_start_time` is
 *  what an exception row carries and what the API matches on; a plain
 *  generated instance only has `start_time`. Same convention the web uses
 *  (`EventDetailModal` → `EventChecklist`). */
function occurrenceStart(instance) {
  return instance?.original_start_time ?? instance?.start_time ?? null;
}

/**
 * Occurrences of `eventId` near `now`, closest first in time order.
 *
 * Returns `[]` rather than throwing when the window is empty or the
 * endpoint refuses: an empty picker is handled by the caller as "fall back
 * to asking about all sessions", which is still a correct write.
 */
async function listOccurrences({ cortex, userId, eventId, now = new Date(), limit = MAX_OCCURRENCES }) {
  let result;
  try {
    result = await cortex.listScheduleInstances(eventId, userId, {
      rangeStart: isoOffsetDays(now, -LOOK_BACK_DAYS),
      rangeEnd: isoOffsetDays(now, LOOK_AHEAD_DAYS),
    });
  } catch {
    return [];
  }

  const starts = (result?.instances ?? [])
    .map(occurrenceStart)
    .filter((value) => typeof value === "string")
    .filter((value) => !Number.isNaN(new Date(value).getTime()));

  // Nearest to now wins a place in the list; the list itself is then shown
  // in time order, because a picker sorted by "distance from now" jumps
  // backwards and forwards and reads as unsorted.
  const nearest = [...new Set(starts)]
    .sort((a, b) => Math.abs(new Date(a) - now) - Math.abs(new Date(b) - now))
    .slice(0, limit);
  return nearest.sort((a, b) => new Date(a) - new Date(b));
}

/**
 * Can this task be written to directly?
 *
 * - `{ ready: true, task }` — an ordinary task; write it.
 * - `{ ready: false, task, event, occurrences }` — a checklist item on a
 *   recurring event; the caller has to ask which session first.
 *
 * `task` may be passed in when the caller already has it (the `*tasks`
 * card holds the list it rendered); a notification button has only an id
 * and pays for one fetch.
 */
async function prepareTaskWrite({ cortex, userId, taskId, task = null, now = new Date() }) {
  const loaded = task ?? (await cortex.getTask(taskId, userId));
  if (!loaded) return { ready: false, missing: true, task: null };

  if (!loaded.related_event_id) return { ready: true, task: loaded };

  // Asking the backend instead of inferring from the task: whether the
  // event recurs is a fact about the *schedule*, and `TaskResponse` does
  // not carry it. `is_recurring` is the same field the web reads.
  const event = await cortex.getSchedule(loaded.related_event_id, userId);
  if (!event?.is_recurring) return { ready: true, task: loaded };

  const occurrences = await listOccurrences({
    cortex,
    userId,
    eventId: loaded.related_event_id,
    now,
  });
  return { ready: false, task: loaded, event, occurrences };
}

/**
 * Do the write.
 *
 * Snooze sets the due date to tomorrow at midnight UTC — the convention
 * `*new` already uses, and for the same reason: `today.py` compares
 * `.date()` on both sides, so the time component never reaches a decision,
 * and inventing one that *looks* precise (23:59, end of the working day)
 * would imply an accuracy the ranking does not have. Which day "tomorrow"
 * is, though, is decided in the user's timezone — see `clock.js`.
 */
async function applyTaskWrite({
  cortex,
  userId,
  taskId,
  intent,
  occurrence = null,
  timezone = DEFAULT_TIMEZONE,
  now = new Date(),
}) {
  if (intent === INTENT.COMPLETE) {
    return { intent, task: await cortex.completeTask(taskId, userId, occurrence) };
  }
  if (intent === INTENT.SNOOZE) {
    const due = tomorrowIsoDate(timezone, now);
    return {
      intent,
      dueDate: due,
      task: await cortex.updateTask(taskId, { due_date: `${due}T00:00:00Z` }, userId, occurrence),
    };
  }
  throw new Error(`unknown task intent: ${intent}`);
}

module.exports = {
  INTENT,
  MAX_OCCURRENCES,
  LOOK_BACK_DAYS,
  LOOK_AHEAD_DAYS,
  occurrenceStart,
  listOccurrences,
  prepareTaskWrite,
  applyTaskWrite,
};
