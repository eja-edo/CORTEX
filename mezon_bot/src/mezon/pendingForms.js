"use strict";

/**
 * Questions waiting for an answer, held between sending an `ask_choice`
 * card and the user submitting it.
 *
 * Why anything is held at all: a form submission comes back as
 * `{ field_id: value }` and nothing else (§VIII bis 7). Rebuilding the
 * "1. <câu hỏi> → <đáp án>" line the web sends back into the conversation
 * needs the question *text*, which is not in that payload and is far too
 * long to smuggle through a `button_id`.
 *
 * In memory, with a TTL, and lost on restart — an accepted trade rather
 * than an oversight. Persisting it would mean a schema, a migration and a
 * cleanup job for state whose entire useful life is the couple of minutes
 * between a question and its answer; the failure mode it avoids is one
 * stale card replying "form này đã hết hạn, bạn trả lời bằng tin nhắn
 * thường nhé", which loses nothing because answering in prose was always
 * allowed anyway.
 *
 * The cap matters for a different reason than the TTL: a user who is sent
 * cards and never answers them would otherwise grow this map for as long
 * as the process lives.
 */

const DEFAULT_TTL_MS = 30 * 60 * 1000;
const DEFAULT_MAX = 200;

class PendingForms {
  constructor({ ttlMs = DEFAULT_TTL_MS, max = DEFAULT_MAX, now = () => Date.now() } = {}) {
    this.ttlMs = ttlMs;
    this.max = max;
    this.now = now;
    this.entries = new Map();
    this._counter = 0;
  }

  _sweep() {
    const cutoff = this.now() - this.ttlMs;
    for (const [id, entry] of this.entries) {
      if (entry.createdAt <= cutoff) this.entries.delete(id);
    }
    // Map iterates in insertion order, so the front is the oldest.
    while (this.entries.size > this.max) {
      const oldest = this.entries.keys().next().value;
      this.entries.delete(oldest);
    }
  }

  /** Store a payload, returning the id to put on the submit button.
   *
   *  Swept *after* the insert, not before: sweeping first leaves the map
   *  one over the cap on every write, since the entry being added is not
   *  yet part of the size it checks. */
  put(payload) {
    const id = `${this.now().toString(36)}${(this._counter++).toString(36)}`;
    this.entries.set(id, { ...payload, createdAt: this.now() });
    this._sweep();
    return id;
  }

  /** Non-destructive on purpose: a double-click on submit must not turn
   *  the second click into "form hết hạn". `delete` is what ends a
   *  form's life, once its answer is actually on its way. */
  get(id) {
    const entry = this.entries.get(id);
    if (!entry) return null;
    if (entry.createdAt <= this.now() - this.ttlMs) {
      this.entries.delete(id);
      return null;
    }
    return entry;
  }

  delete(id) {
    this.entries.delete(id);
  }

  get size() {
    return this.entries.size;
  }
}

module.exports = { PendingForms };
