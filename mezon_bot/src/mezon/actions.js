"use strict";

/**
 * The `button_id` namespace.
 *
 * Every interactive control this bot sends carries an id that says both
 * *what* the button does and *which* thing it does it to, because that id
 * is the only context a `message_button_clicked` event brings back — the
 * event has no memory of the message that carried it beyond
 * `message_id`. Encoding the target here rather than looking it up means
 * plan approval survives a bot restart: the id is self-describing.
 *
 * Ids stay short deliberately. A UUID is already 36 characters and
 * nothing documents a `button_id` length limit, so the prefixes are two
 * letters rather than readable words.
 *
 * `parse` returning `null` is the normal case, not an error: the M0 probe
 * (docs/mezon-bot-plan.md §VIII bis 8b) recorded that a SELECT fires this
 * same event on every change, with the *select's* own id as `button_id`.
 * A handler that treats unknown ids as failures would log an error every
 * time a user opened a dropdown.
 */

const PREFIXES = {
  "pa:": "plan_approve",
  "pr:": "plan_reject",
  "as:": "ask_submit",
  "ms:": "model_submit",
  "tc:": "task_complete",
  "tn:": "task_create",
  "mu:": "mute_submit",
  "ir:": "inbox_read_all",
};

const KINDS = Object.fromEntries(Object.entries(PREFIXES).map(([p, k]) => [k, p]));

/** `kind` + the id it targets → the `button_id` to put on the control. */
function actionId(kind, targetId) {
  const prefix = KINDS[kind];
  if (!prefix) throw new Error(`unknown action kind: ${kind}`);
  return `${prefix}${targetId}`;
}

/** `button_id` → `{ kind, targetId }`, or `null` when this is not one of
 *  ours. */
function parseActionId(buttonId) {
  if (typeof buttonId !== "string") return null;
  for (const [prefix, kind] of Object.entries(PREFIXES)) {
    if (buttonId.startsWith(prefix)) {
      const targetId = buttonId.slice(prefix.length);
      return targetId ? { kind, targetId } : null;
    }
  }
  return null;
}

module.exports = { actionId, parseActionId };
