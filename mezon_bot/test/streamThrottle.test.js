"use strict";

/**
 * Tests for `StreamThrottle` — the R3 coalescing logic, in isolation from
 * both the SDK and `router.js`. Real short timers are used (matching this
 * repo's no-mocking-library convention, e.g. `link.test.js`'s countdown),
 * with small millisecond values so the suite stays fast.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { StreamThrottle } = require("../src/mezon/streamThrottle");

function makeRecorder(opts = {}) {
  const calls = [];
  const throttle = new StreamThrottle({
    edit: async (text) => { calls.push(text); },
    firstEditDelayMs: 30,
    intervalMs: 40,
    charThreshold: 10,
    ...opts,
  });
  return { throttle, calls };
}

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

test("the first edit is delayed, not immediate — the placeholder stays up until then", async () => {
  const { throttle, calls } = makeRecorder();

  throttle.push("hi");
  assert.equal(calls.length, 0, "must not edit synchronously on the first push");

  await wait(50);
  assert.deepEqual(calls, ["hi"]);
});

test("edits inside the interval and under the char threshold are coalesced, not sent per push", async () => {
  const { throttle, calls } = makeRecorder({ intervalMs: 1000, charThreshold: 1000 });

  throttle.push("a");
  throttle.push("b");
  throttle.push("c");
  await wait(50); // past firstEditDelayMs (30ms), well under intervalMs (1000ms)

  assert.deepEqual(calls, ["abc"], "one edit carrying everything pushed so far, not three");
});

test("crossing the char threshold forces the next edit even before the interval elapses", async () => {
  // Only the *first* edit is purely time-gated (R3: "~500ms, đủ để có nội
  // dung"). Every edit after that races time against character count —
  // this test is about that second regime, so it primes the throttle past
  // its first edit before asserting on the threshold.
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 5, intervalMs: 10_000, charThreshold: 5 });

  throttle.push("first");
  await wait(15);
  assert.deepEqual(calls, ["first"], "primed: one edit already happened");

  throttle.push("second chunk over threshold");
  await wait(20);

  assert.equal(calls.length, 2);
  assert.equal(calls[1], "firstsecond chunk over threshold");
});

test("flush edits immediately with whatever is buffered, cancelling any pending timer", async () => {
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 10_000, intervalMs: 10_000 });

  throttle.push("final answer");
  await throttle.flush();

  assert.deepEqual(calls, ["final answer"]);

  // The cancelled 10s timer must not fire a second, redundant edit later.
  await wait(30);
  assert.deepEqual(calls, ["final answer"]);
});

test("an edit that is still in flight collapses a concurrent request into one rerun, not two overlapping calls", async () => {
  let inFlight = 0;
  let maxConcurrent = 0;
  const calls = [];
  const throttle = new StreamThrottle({
    edit: async (text) => {
      inFlight++;
      maxConcurrent = Math.max(maxConcurrent, inFlight);
      await wait(30);
      calls.push(text);
      inFlight--;
    },
    firstEditDelayMs: 5,
    intervalMs: 5,
    charThreshold: 1000,
  });

  throttle.push("a");
  await wait(10); // first edit ("a") is now in flight
  throttle.push("b"); // due immediately (elapsed already reset by nothing yet, but not in-flight-safe)
  await wait(100);

  assert.equal(maxConcurrent, 1, "edit() must never be called concurrently with itself");
  assert.equal(calls[calls.length - 1], "ab", "the rerun must carry the latest buffer, not a stale snapshot");
});

test("replace rewrites the whole body instead of appending — the thinking timeline re-renders, it does not grow", async () => {
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 30, intervalMs: 1000 });

  throttle.replace("🧠 nghĩ");
  throttle.replace("🧠 nghĩ thêm");
  throttle.replace("🧠 nghĩ thêm nữa");
  assert.equal(calls.length, 0, "must not edit synchronously on each re-render");

  await wait(50);
  assert.deepEqual(calls, ["🧠 nghĩ thêm nữa"], "one edit carrying the newest render, not three");
});

test("replace with immediate:true bypasses the throttle — a tool step happens once per call and is worth showing at once", async () => {
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 10_000 });

  throttle.replace("🔧 `search_notes`", { immediate: true });
  await wait(10);

  assert.deepEqual(calls, ["🔧 `search_notes`"]);
});

test("replacing with an identical body is not a second edit", async () => {
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 5 });

  throttle.replace("🔧 `search_notes`", { immediate: true });
  await wait(20);
  const before = calls.length;

  throttle.replace("🔧 `search_notes`", { immediate: true });
  await wait(20);
  assert.equal(calls.length, before);
});

test("push is replace's append case — the two share one set of timing rules", async () => {
  const { throttle, calls } = makeRecorder({ firstEditDelayMs: 5, intervalMs: 10_000, charThreshold: 1000 });

  throttle.push("một");
  throttle.push(" hai");
  await wait(20);

  assert.deepEqual(calls, ["một hai"]);
  assert.equal(throttle.buffer, "một hai");
});
