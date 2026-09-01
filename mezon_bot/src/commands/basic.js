"use strict";

/**
 * Commands that need no Cortex identity.
 *
 * `*ping` is deliberately more than a pong: it reports whether the bot can
 * reach the backend and whether this account is linked. During the probe
 * phase, "the bot is broken" turned out three separate times to mean three
 * different things — socket fine but client stale, backend unreachable,
 * account not linked. One command that says which is worth more than a
 * cheerful "pong".
 */

const { notice } = require("../mezon/embed");

const pingCommand = {
  name: "ping",
  description: "Kiểm tra bot và kết nối tới Cortex",
  usage: "*ping",
  requiresLink: false,

  async run({ cortex, identity, reply }) {
    const backendUp = await cortex.health();
    await reply(
      notice("🏓 pong", null, {
        fields: [
          { name: "Bot", value: "✅ đang chạy", inline: true },
          { name: "Cortex", value: backendUp ? "✅ kết nối được" : "❌ không kết nối được", inline: true },
          {
            name: "Tài khoản",
            value: identity?.linked ? "✅ đã liên kết" : "⚠️ chưa liên kết (`*link <mã>`)",
            inline: true,
          },
        ],
      })
    );
  },
};

const helpCommand = {
  name: "help",
  aliases: ["h"],
  description: "Danh sách lệnh",
  usage: "*help",
  requiresLink: false,

  async run({ registry, reply, prefix, identity }) {
    const lines = registry
      .list()
      .map((c) => `\`${prefix}${c.name}\` — ${c.description}`)
      .join("\n");

    // Named so the reader can go make the icons: a clan icon called `today`
    // makes `:today:` run `*today`, and Mezon's own icon picker then does
    // the autocompleting. Worth one line here because the feature is
    // invisible until someone knows the names to create.
    const iconHint = "Mỗi lệnh cũng chạy được bằng icon cùng tên — `:today:` = `" + prefix + "today`.";

    const hint = identity?.linked
      ? "Nhắn bình thường (không có dấu " + prefix + ") để trò chuyện với AI."
      : `Chưa liên kết tài khoản. Lấy mã trên web rồi gõ \`${prefix}link <mã>\`.`;

    await reply(notice("Cortex bot", `${lines}\n\n${iconHint}\n${hint}`));
  },
};

module.exports = { pingCommand, helpCommand };
