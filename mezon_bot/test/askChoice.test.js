"use strict";

/**
 * Tests for the `ask_choice` card — rendering the questions as a Mezon
 * form, and reading a submission back into the string that becomes the
 * user's next chat message.
 *
 * The encoding facts asserted here (single radio → string, multi radio →
 * string[], untouched field absent entirely) are the M0 probe's measured
 * output against the live gateway, not assumptions — see
 * docs/mezon-bot-plan.md §VIII bis 7 and 8.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { renderAskChoice, readAnswers, renderAnsweredCard } = require("../src/mezon/askChoice");
const { parseActionId } = require("../src/mezon/actions");

const QUESTIONS = [
  {
    id: "q1",
    question: "Deadline khi nào?",
    options: [{ label: "Thứ 6 này" }, { label: "Tuần sau" }],
  },
  {
    id: "q2",
    question: "Ưu tiên ra sao?",
    allow_multiple: true,
    options: [{ label: "Cao" }, { label: "Thường" }],
  },
];

function fieldsOf(content) {
  return content.embed[0].fields;
}

test("each question becomes a radio field, with a free-text escape next to it", () => {
  const content = renderAskChoice(QUESTIONS, "form-1");
  const fields = fieldsOf(content);

  assert.equal(fields.length, 4, "two questions × (radio + 'Ý khác')");
  assert.equal(fields[0].inputs.id, "q0");
  assert.equal(fields[1].inputs.id, "qc0", "the free-text alternative the tool schema promises the model exists");
  assert.match(fields[0].name, /1\. Deadline khi nào\?/);
});

test("an option's value is its label — the model must read back the words it wrote", () => {
  const options = fieldsOf(renderAskChoice(QUESTIONS, "form-1"))[0].inputs.component;
  assert.deepEqual(
    options.map((o) => o.value),
    ["Thứ 6 này", "Tuần sau"]
  );
});

test("a multi-answer question gets distinct option names; a single-answer one gets none", () => {
  // The client decides single vs multi by comparing the first two
  // options' `name` (EmbedOptionRatio.tsx). Identical names silently
  // produce a single-choice control — a failure with no error anywhere.
  const fields = fieldsOf(renderAskChoice(QUESTIONS, "form-1"));

  const single = fields[0].inputs.component;
  assert.equal(single[0].name, undefined, "single-choice must set no name at all");

  const multi = fields[2].inputs.component;
  assert.notEqual(multi[0].name, multi[1].name, "multi-choice is only multi if the first two names differ");
});

test("the submit button carries an id the router can route on", () => {
  const content = renderAskChoice(QUESTIONS, "form-1");
  const button = content.components[0].components[0];
  assert.deepEqual(parseActionId(button.id), { kind: "ask_submit", targetId: "form-1" });
});

test("a submission becomes the same 'n. câu hỏi → đáp án' text the web sends", () => {
  // Not cosmetic: this string *is* the next user message, and the model
  // reading the same shape on both surfaces is what keeps a conversation
  // that moved between them coherent.
  const { answers, summaryText, missing } = readAnswers(QUESTIONS, {
    q0: "Tuần sau",
    q1: ["Cao"],
  });

  assert.deepEqual(missing, []);
  assert.deepEqual(answers, { q1: "Tuần sau", q2: "Cao" });
  assert.equal(summaryText, "1. Deadline khi nào? → Tuần sau\n2. Ưu tiên ra sao? → Cao");
});

test("free text is appended to whatever was picked, not treated as a separate answer", () => {
  const { answers } = readAnswers(QUESTIONS, {
    q0: "Tuần sau",
    q1: ["Cao"],
    qc1: "  hoặc để tôi tự xếp  ",
  });
  assert.equal(answers.q2, "Cao, hoặc để tôi tự xếp", "trimmed, and joined with the picks");
});

test("free text alone answers a question — the escape hatch has to work without picking anything", () => {
  const { answers, missing } = readAnswers(QUESTIONS, { qc0: "cuối tháng", q1: ["Thường"] });
  assert.deepEqual(missing, []);
  assert.equal(answers.q1, "cuối tháng");
});

test("a question with neither a pick nor free text is reported as missing, by its number", () => {
  // An untouched field is absent from the payload, so "not answered" and
  // "answered blank" are one event here. The web gates its submit button
  // on all questions being answered; a Mezon button cannot be gated, so
  // the check lands after the click.
  const { missing, summaryText } = readAnswers(QUESTIONS, { q0: "Tuần sau" });
  assert.deepEqual(missing, [2]);
  assert.ok(!summaryText.includes("Ưu tiên"), "an unanswered question must not reach the model as answered");
});

test("an empty submission — every field untouched — reports every question, not a crash", () => {
  const { missing } = readAnswers(QUESTIONS, {});
  assert.deepEqual(missing, [1, 2]);
});

test("the answered card carries no buttons — a submitted form must stop being submittable", () => {
  const content = renderAnsweredCard(QUESTIONS, { q1: "Tuần sau", q2: "Cao" });
  assert.equal(content.components, undefined);
  assert.match(JSON.stringify(content), /Tuần sau/);
});
