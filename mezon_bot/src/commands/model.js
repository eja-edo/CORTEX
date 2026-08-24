"use strict";

/**
 * `*model` — switch which model answers in Mezon.
 *
 * Thin, per the registry's first rule: it fetches the catalogue and the
 * user's current choice, renders them, and stores nothing itself. The
 * choice lives in `user_preferences.chat_model` on the backend rather
 * than in this process, because a setting that silently resets whenever
 * the bot restarts is worse than no setting — and bot restarts are
 * routine (see the M1 notes on deploys).
 *
 * The form's questions are held in `pendingForms` only long enough to
 * turn a submitted id back into a label for the confirmation; the choice
 * itself is already safe on the backend by then.
 */

const { renderModelPicker } = require("../mezon/modelCard");

const modelCommand = {
  name: "model",
  description: "Chọn model AI dùng trong Mezon",
  usage: "*model",
  requiresLink: true,

  async run({ cortex, identity, pendingForms, reply }) {
    const [models, prefs] = await Promise.all([
      cortex.listModels(identity.userId),
      // A failure here costs the "đang dùng" marker, not the command:
      // picking a model must still work when the current one is unknown.
      cortex.getPreferences(identity.userId).catch(() => null),
    ]);

    if (!Array.isArray(models) || models.length === 0) {
      await reply("Không lấy được danh sách model từ Cortex. Thử lại sau ít phút.");
      return;
    }

    const formId = pendingForms.put({ models });
    await reply(renderModelPicker(models, prefs?.chat_model ?? null, formId));
  },
};

module.exports = { modelCommand };
