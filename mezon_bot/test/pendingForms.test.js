"use strict";

/**
 * Tests for `PendingForms` — the in-memory hold between sending an
 * `ask_choice` card and the user submitting it. A fake clock is injected
 * rather than sleeping, since the real TTL is half an hour.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { PendingForms } = require("../src/mezon/pendingForms");

function makeClock(start = 1_000_000) {
  let now = start;
  return { now: () => now, advance: (ms) => { now += ms; } };
}

test("what goes in comes back out, under an id the caller did not have to invent", () => {
  const forms = new PendingForms();
  const id = forms.put({ questions: [{ id: "q1" }] });

  assert.equal(typeof id, "string");
  assert.deepEqual(forms.get(id).questions, [{ id: "q1" }]);
});

test("get is non-destructive — a double-click on submit must not turn the second click into 'hết hạn'", () => {
  const forms = new PendingForms();
  const id = forms.put({ questions: [] });

  assert.ok(forms.get(id));
  assert.ok(forms.get(id), "still there");

  forms.delete(id);
  assert.equal(forms.get(id), null, "and gone once the answer is actually on its way");
});

test("an entry past its TTL reads as absent", () => {
  const clock = makeClock();
  const forms = new PendingForms({ ttlMs: 1000, now: clock.now });
  const id = forms.put({ questions: [] });

  clock.advance(999);
  assert.ok(forms.get(id));

  clock.advance(2);
  assert.equal(forms.get(id), null);
});

test("the map cannot grow without bound — a user who never answers must not leak the process's memory", () => {
  const forms = new PendingForms({ max: 3 });
  const ids = Array.from({ length: 5 }, () => forms.put({ questions: [] }));

  assert.ok(forms.size <= 3);
  assert.equal(forms.get(ids[0]), null, "the oldest is what gets evicted");
  assert.ok(forms.get(ids[4]), "the newest survives");
});

test("expired entries are swept on write, not left for a get that may never come", () => {
  const clock = makeClock();
  const forms = new PendingForms({ ttlMs: 1000, now: clock.now });
  forms.put({ questions: [] });
  clock.advance(2000);

  forms.put({ questions: [] });
  assert.equal(forms.size, 1);
});
