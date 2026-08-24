"use strict";

/**
 * `ask_choice` as a Mezon form.
 *
 * The web renders `AskChoiceCard.tsx`: one question at a time, options as
 * buttons, always an "Ý khác" free-text escape, and a submit that sends
 * the picks back into the conversation as the user's next message. There
 * is no endpoint behind it — `ask_user_choice.py` says so outright ("the
 * answer flows straight back into the conversation as the user's next
 * chat message"), which is what makes this portable to chat at all: a
 * radio group plus a button reproduces it exactly.
 *
 * Two details are copied deliberately rather than improved on:
 *
 * - **The option's label is its value.** The web puts the label itself in
 *   `answers[q.id]`, so the model reads back the words it wrote. Sending
 *   an index or a synthetic key instead would hand it something it never
 *   said.
 * - **Free text is always available**, per the tool schema's own
 *   instruction to the model ("The UI always also lets the user type
 *   their own free-text answer, so don't add a generic 'other/khác'
 *   option yourself"). Dropping it here would make that instruction a
 *   lie on this surface and leave the user with no way out of a bad set
 *   of options.
 *
 * The submitted summary keeps the web's exact wording — `1. <câu hỏi> →
 * <đáp án>` — because that string is not cosmetic: it *is* the next user
 * message, and both surfaces feeding the model the same shape is what
 * keeps a conversation that moved from web to Mezon coherent.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");
const { getList, getText } = require("./interactions");

const choiceFieldId = (index) => `q${index}`;
const customFieldId = (index) => `qc${index}`;

/** Mezon caps nothing here, but the tool schema does: 1-4 questions, 2-6
 *  options each. Cutting at the schema's own maximum keeps a malformed
 *  payload from producing an unusable wall of a form. */
const MAX_QUESTIONS = 4;
const MAX_OPTIONS = 6;

function renderAskChoice(questions, formId) {
  const shown = questions.slice(0, MAX_QUESTIONS);
  const form = new FormBuilder("❓ Cần bạn chọn giúp");
  form.description(
    shown.length > 1
      ? "Chọn đáp án cho từng câu rồi bấm Gửi."
      : "Chọn đáp án rồi bấm Gửi."
  );

  shown.forEach((question, index) => {
    const options = (question.options ?? []).slice(0, MAX_OPTIONS).map((option) => ({
      label: option.label,
      value: option.label,
      description: option.description,
    }));
    form.radio(
      choiceFieldId(index),
      `${index + 1}. ${question.question}`,
      options,
      { multiple: Boolean(question.allow_multiple) }
    );
    form.textInput(customFieldId(index), `Ý khác (câu ${index + 1})`, {
      placeholder: "bỏ trống nếu đã chọn ở trên",
    });
  });

  form.button(actionId("ask_submit", formId), "Gửi", STYLE.PRIMARY);
  return form.build();
}

/**
 * Submitted form values → what to send back into the conversation.
 *
 * `missing` is the questions with neither a pick nor free text, and it
 * exists because of §VIII bis 8b: an untouched field is *absent* from the
 * payload, so "no answer" and "answered with nothing" are the same event
 * here. The web gates its submit button on all questions being answered;
 * a Mezon button cannot be gated, so the check moves to this side of the
 * click.
 */
function readAnswers(questions, values) {
  const shown = questions.slice(0, MAX_QUESTIONS);
  const answers = {};
  const lines = [];
  const missing = [];

  shown.forEach((question, index) => {
    const picks = getList(values, choiceFieldId(index));
    const custom = (getText(values, customFieldId(index), "") ?? "").trim();
    const parts = custom ? [...picks, custom] : picks;
    const answer = parts.filter(Boolean).join(", ");

    if (!answer) {
      missing.push(index + 1);
      return;
    }
    answers[question.id] = answer;
    lines.push(`${index + 1}. ${question.question} → ${answer}`);
  });

  return { answers, summaryText: lines.join("\n"), missing };
}

/** What the card becomes once answered — the buttons are gone with it,
 *  which is how a submitted form stops being submittable. Mirrors the
 *  web's `ask-choice-card--locked`. */
function renderAnsweredCard(questions, answers) {
  const fields = questions
    .slice(0, MAX_QUESTIONS)
    .filter((question) => answers[question.id])
    .map((question, index) => ({
      name: `${index + 1}. ${question.question}`,
      value: `✅ ${answers[question.id]}`,
    }));
  return notice("❓ Đã trả lời", null, { fields });
}

module.exports = {
  renderAskChoice,
  readAnswers,
  renderAnsweredCard,
  choiceFieldId,
  customFieldId,
  MAX_QUESTIONS,
  MAX_OPTIONS,
};
