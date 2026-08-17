"use strict";

/**
 * `*link <code>` — attach this Mezon account to a Cortex account.
 *
 * The code is minted in the web app, where the person is already logged
 * in, and typed here. The reverse direction would be a vulnerability
 * rather than a convenience: Mezon user ids are visible to everyone in a
 * clan, so anything that accepted an id as proof would let a stranger
 * claim someone else's account.
 *
 * Nothing about linking is decided in the bot. It forwards the code and
 * the sender's id; the backend decides whose account that code belongs to.
 */

const { notice, STYLE } = require("../mezon/embed");
const { CortexError } = require("../cortex");
const { logger } = require("../logger");

const CODE_PATTERN = /^\d{4,12}$/;

const linkCommand = {
  name: "link",
  description: "Liên kết tài khoản Mezon với Cortex — `*link <mã>`",
  usage: "*link 123456",
  // The one command that must work *before* an identity exists.
  requiresLink: false,

  async run({ args, message, cortex, reply, prefix }) {
    const code = args.trim();

    if (!code) {
      await reply(
        "Cần mã liên kết.\n" +
          "Mở Cortex trên web → Settings → Liên kết Mezon để lấy mã 6 số, rồi gõ:\n" +
          `\`${prefix}link 123456\``
      );
      return;
    }

    // Shape-checked here only to give a clearer message than the backend's
    // deliberately vague "invalid or expired" — the real decision, and the
    // rejection that matters, still happens server-side.
    if (!CODE_PATTERN.test(code)) {
      await reply("Mã liên kết chỉ gồm chữ số. Kiểm tra lại mã trên web.");
      return;
    }

    try {
      const channel = await cortex.redeemLinkCode({
        code,
        address: message.senderId,
        label: message.displayName || message.username || "Mezon",
      });

      logger.info("account linked", { mezonUserId: message.senderId, channelId: channel.id });

      await reply(
        notice(
          "✅ Đã liên kết",
          "Từ giờ Cortex có thể nhắn cho bạn ở đây, và bạn nhắn thẳng cho tôi để trò chuyện.",
          {
            fields: [
              { name: "Tài khoản Mezon", value: message.displayName || message.username || message.senderId },
              { name: "Mức nhắc mặc định", value: channel.min_level ?? "recommend", inline: true },
              { name: "Tắt lúc nào cũng được", value: "Web → Settings → Notifications", inline: true },
            ],
          }
        )
      );
    } catch (err) {
      if (err instanceof CortexError && err.isClientError) {
        // The backend refuses to say which of "unknown / expired / already
        // used" happened, so neither do we — all three mean the same thing
        // to an honest user, and the distinction only helps a guesser.
        await reply(`❌ ${err.message}\nLấy mã mới trên web rồi thử lại.`);
        return;
      }
      logger.error("link failed", { error: err?.message });
      await reply("❌ Không kết nối được tới Cortex. Thử lại sau ít phút.");
    }
  },
};

module.exports = { linkCommand };
