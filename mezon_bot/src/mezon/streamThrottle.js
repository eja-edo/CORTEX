"use strict";

/**
 * Coalescing token buffer for R3 ("giả-realtime bằng message.update").
 *
 * Three rules are load-bearing here, each one a documented way this breaks
 * if skipped (docs/mezon-bot-plan.md §V/R3):
 *
 * 1. Throttling is mandatory, not an optimisation. The SDK's own
 *    `AsyncThrottleQueue` only *queues* edits, it doesn't *coalesce* them —
 *    an edit per token would grow that queue without bound and the message
 *    would visibly stutter. This class is what decides which edits are
 *    even worth queuing.
 * 2. The first edit is delayed (`firstEditDelayMs`), not immediate — the
 *    placeholder message ("⏳ đang nghĩ…") is what the caller sends before
 *    any of this runs; overwriting it the instant the first token arrives
 *    would just be a different flavour of "nothing happens for a while".
 * 3. A caller that re-renders rather than appends uses `replace`, not
 *    `push`. The thinking timeline is the case: every reasoning token
 *    changes the whole block, so there is nothing to append — but the
 *    edits still have to be coalesced exactly like a token stream, since
 *    they arrive just as fast.
 *
 * No SDK dependency: `edit` is injected, so this is testable with a fake
 * function and no live socket — same convention as every other test in
 * this repo.
 */

const DEFAULT_FIRST_EDIT_DELAY_MS = 500;
const DEFAULT_INTERVAL_MS = 1000;
const DEFAULT_CHAR_THRESHOLD = 80;

class StreamThrottle {
  constructor({
    edit,
    firstEditDelayMs = DEFAULT_FIRST_EDIT_DELAY_MS,
    intervalMs = DEFAULT_INTERVAL_MS,
    charThreshold = DEFAULT_CHAR_THRESHOLD,
  }) {
    this.edit = edit;
    this.firstEditDelayMs = firstEditDelayMs;
    this.intervalMs = intervalMs;
    this.charThreshold = charThreshold;

    this.buffer = "";

    this._lastEditedAt = null;
    this._lastEditedLength = 0;
    this._timer = null;
    this._editing = false;
    this._pendingRerun = false;
  }

  /** Serialises calls to `edit` — an SDK `message.update()` racing against
   *  itself is not a case worth risking, so a call that lands mid-edit is
   *  collapsed into "run once more after this one finishes" rather than
   *  fired concurrently. */
  async _doEdit() {
    if (this._editing) {
      this._pendingRerun = true;
      return;
    }
    this._editing = true;
    try {
      await this.edit(this.buffer);
      this._lastEditedAt = Date.now();
      this._lastEditedLength = this.buffer.length;
    } finally {
      this._editing = false;
      if (this._pendingRerun) {
        this._pendingRerun = false;
        await this._doEdit();
      }
    }
  }

  _scheduleTimer(delayMs) {
    if (this._timer) return;
    this._timer = setTimeout(() => {
      this._timer = null;
      void this._doEdit();
    }, Math.max(delayMs, 0));
  }

  _clearTimer() {
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  }

  /** A chunk of token text arrived. */
  push(chunk) {
    if (!chunk) return;
    this.replace(this.buffer + chunk);
  }

  /**
   * The whole body changed — for callers that re-render instead of
   * appending.
   *
   * `immediate` is the difference between a reasoning token and a tool
   * step. Reasoning arrives at the same rate as answer tokens, so it
   * rides the throttle like one; a tool step happens once per call, so
   * showing it the instant it lands is both cheap and the point.
   */
  replace(body, { immediate = false } = {}) {
    const next = body ?? "";
    if (next === this.buffer) return;
    this.buffer = next;

    if (immediate) {
      this._clearTimer();
      void this._doEdit();
      return;
    }
    if (this._lastEditedAt === null) {
      this._scheduleTimer(this.firstEditDelayMs);
      return;
    }

    const elapsed = Date.now() - this._lastEditedAt;
    const grown = this.buffer.length - this._lastEditedLength;
    if (elapsed >= this.intervalMs || grown >= this.charThreshold) {
      this._clearTimer();
      void this._doEdit();
    } else {
      this._scheduleTimer(this.intervalMs - elapsed);
    }
  }

  /** Stream ended (`done`, or an error path) — edit immediately with
   *  whatever is buffered, bypassing the throttle. A no-op if nothing was
   *  ever pushed: an empty stream must leave the placeholder alone for
   *  the caller to replace with its own "no answer" message, not blank it
   *  out first. */
  async flush() {
    this._clearTimer();
    if (!this.buffer) return;
    await this._doEdit();
  }
}

module.exports = { StreamThrottle };
