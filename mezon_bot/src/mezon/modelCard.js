"use strict";

/**
 * The `*model` picker.
 *
 * A radio of whatever `GET /api/agent/models` returns, plus a button.
 * Nothing about the model list is decided here — the catalogue lives in
 * the backend (`model_catalog.py`) and the bot renders what it is given,
 * which is the 4.2 Trigger Catalog lesson applied to this surface: a
 * hard-coded list in a client goes stale the first time the catalogue
 * moves, and nobody notices until someone picks a model that no longer
 * exists.
 *
 * The current choice is marked in the option's own label rather than
 * pre-selected, because Mezon's radio field has no "selected" state to
 * set — `addRadioField` takes options, a description and a max, and that
 * is all (see `FormBuilder.radio`). Saying which one is live in the text
 * is the honest version of a control that cannot show it.
 */

const { FormBuilder, STYLE, notice } = require("./embed");
const { actionId } = require("./actions");

const MODEL_FIELD_ID = "model";

/**
 * `models` is `[{ id, label }]` straight from the backend; `currentId` is
 * the user's stored choice, or null when they have never picked one.
 */
function renderModelPicker(models, currentId, formId) {
  const form = new FormBuilder("🤖 Chọn model");
  const current = models.find((m) => m.id === currentId);
  form.description(
    current
      ? `Đang dùng: **${current.label}**. Chọn model khác rồi bấm Lưu.`
      : "Đang dùng model mặc định. Chọn model rồi bấm Lưu."
  );

  form.radio(
    MODEL_FIELD_ID,
    "Model",
    models.map((model) => ({
      label: model.id === currentId ? `${model.label} — đang dùng` : model.label,
      value: model.id,
      description: model.id,
    })),
    { multiple: false }
  );

  form.button(actionId("model_submit", formId), "Lưu", STYLE.PRIMARY);
  return form.build();
}

/**
 * What the picker becomes once saved — no buttons, so the choice reads as
 * settled rather than still open.
 *
 * Says the change applies to Mezon only. That is not a caveat to bury:
 * the web keeps its own picker, so a user who sets a model here and then
 * sees a different one selected on the web has not hit a bug, and the one
 * sentence that prevents that conclusion belongs where the choice is
 * made.
 */
function renderModelSaved(model) {
  return notice(
    "🤖 Đã đổi model",
    `Từ giờ các câu trả lời trong Mezon sẽ dùng **${model.label}**.`,
    {
      fields: [{ name: "Model id", value: `\`${model.id}\`` }],
      color: "#2ea043",
    }
  );
}

module.exports = { renderModelPicker, renderModelSaved, MODEL_FIELD_ID };
