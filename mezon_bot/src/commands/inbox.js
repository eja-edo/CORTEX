"use strict";

/**
 * `*inbox` — the notifications Cortex has sent, and a way to clear them.
 *
 * Reachable from the bot because the bot is often what delivered them: a
 * notification a user was DM'd but can only mark read on the web is a
 * to-do the bot created for them.
 */

const { renderInbox } = require("../mezon/inboxCards");

const inboxCommand = {
  name: "inbox",
  description: "Thông báo gần đây",
  usage: "*inbox",
  requiresLink: true,

  async run({ cortex, identity, pendingForms, reply }) {
    const result = await cortex.listNotifications(identity.userId, { limit: 10 });
    const items = Array.isArray(result?.items) ? result.items : [];
    const formId = pendingForms.put({ notificationCount: items.filter((n) => !n.read_at).length });
    await reply(renderInbox(items, formId));
  },
};

module.exports = { inboxCommand };
