"use strict";

/**
 * `*today` and `*next` — read-only, one API call each.
 *
 * Two commands rather than one with a flag because they answer different
 * questions and the backend serves them from different endpoints:
 * `/today` is the screen ("what does today look like"), `/planning/
 * next-action` is the decision ("what do I do right now"), and the second
 * carries the at-risk list the first doesn't.
 *
 * Neither interprets the response. `state` is served precisely so a
 * client never has to infer one, and the `impact` sentences are the
 * product's actual output — rendering them verbatim is the whole job.
 */

const { renderAgenda } = require("../mezon/agendaCard");

const todayCommand = {
  name: "today",
  aliases: ["hn"],
  description: "Hôm nay có gì cần làm",
  usage: "*today",
  requiresLink: true,

  async run({ cortex, identity, reply }) {
    const data = await cortex.getToday(identity.userId);
    await reply(renderAgenda(data, { title: "📅 Hôm nay" }));
  },
};

const nextCommand = {
  name: "next",
  description: "Nên làm gì tiếp theo",
  usage: "*next",
  requiresLink: true,

  async run({ cortex, identity, reply }) {
    const data = await cortex.getNextAction(identity.userId);
    await reply(renderAgenda(data, { title: "➡️ Làm gì tiếp theo" }));
  },
};

module.exports = { todayCommand, nextCommand };
