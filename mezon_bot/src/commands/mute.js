"use strict";

/**
 * `*mute` — turn off a kind of nudge.
 *
 * The bot's job is to interrupt people, and this is the answer to the
 * interruption. Without it, "stop telling me this" means opening the web
 * app, and the plan lists "thông báo DM gây phiền" as a live risk (§VII)
 * whose only other resolution is the user blocking the bot.
 *
 * `*mute task.overdue` mutes directly — every notification prints its
 * `reason_key` in the footer for exactly this reason, so the string is
 * already in front of the user. Bare `*mute` lists what is on.
 */

const { renderMutePicker, renderMuted } = require("../mezon/inboxCards");

const muteCommand = {
  name: "mute",
  description: "Tắt một loại nhắc",
  usage: "*mute [reason_key]",
  requiresLink: true,

  async run({ cortex, identity, args, pendingForms, reply }) {
    const reasons = await cortex.listReasonPreferences(identity.userId);
    const list = Array.isArray(reasons) ? reasons : [];
    const wanted = args.trim();

    if (wanted) {
      const reason = list.find((r) => r.reason_key === wanted);
      if (!reason) {
        await reply(
          `Không có loại nhắc \`${wanted}\`. Gõ \`*mute\` để xem danh sách đang bật.`
        );
        return;
      }
      if (reason.enabled === false) {
        await reply(`\`${wanted}\` đang tắt sẵn rồi.`);
        return;
      }
      await cortex.setReasonEnabled(wanted, false, identity.userId);
      await reply(renderMuted(reason));
      return;
    }

    const formId = pendingForms.put({ reasons: list });
    await reply(renderMutePicker(list, formId));
  },
};

module.exports = { muteCommand };
