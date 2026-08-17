"use strict";

/**
 * Command routing.
 *
 * Two rules encode decisions from the plan rather than convenience:
 *
 * 1. **Commands are a thin shell.** A handler's job is to parse arguments
 *    and call Cortex. The moment one decides what a valid task is, or what
 *    a date means, the bot has taken a decision away from the backend that
 *    owns permission checks, the revert snapshot store, and the Attention
 *    Gate.
 *
 * 2. **`requiresLink` is enforced here, once.** Every command except
 *    linking and help needs a verified Cortex identity, and an identity
 *    check that each handler is trusted to remember is one that eventually
 *    gets forgotten.
 */

const { logger } = require("../logger");

class CommandRegistry {
  constructor({ prefix }) {
    this.prefix = prefix;
    this.commands = new Map();
  }

  register(command) {
    this.commands.set(command.name, command);
    for (const alias of command.aliases ?? []) {
      this.commands.set(alias, command);
    }
    return this;
  }

  /** Distinct list, aliases collapsed — for `*help`. */
  list() {
    return [...new Set(this.commands.values())];
  }

  /**
   * Split a raw message into a command and its argument string.
   *
   * Returns `null` for anything that is not a command, which is how the
   * router tells "run this" from "hand the whole message to the AI" — the
   * default path for plain DMs.
   */
  parse(text) {
    const trimmed = (text ?? "").trim();
    if (!trimmed.startsWith(this.prefix)) return null;

    const withoutPrefix = trimmed.slice(this.prefix.length);
    const spaceIndex = withoutPrefix.search(/\s/);
    const name = (spaceIndex === -1 ? withoutPrefix : withoutPrefix.slice(0, spaceIndex))
      .trim()
      .toLowerCase();
    if (!name) return null;

    const args = spaceIndex === -1 ? "" : withoutPrefix.slice(spaceIndex + 1).trim();
    return { name, args };
  }

  async dispatch(parsed, ctx) {
    const command = this.commands.get(parsed.name);
    if (!command) {
      await ctx.reply(
        `Không có lệnh \`${this.prefix}${parsed.name}\`. Gõ \`${this.prefix}help\` để xem danh sách.`
      );
      return { handled: true, unknown: true };
    }

    if (command.requiresLink && !ctx.identity?.linked) {
      await ctx.reply(
        "Tài khoản Mezon này chưa liên kết với Cortex.\n" +
          `Mở Cortex trên web → Settings → Liên kết Mezon để lấy mã, rồi gõ \`${this.prefix}link <mã>\`.`
      );
      return { handled: true, unlinked: true };
    }

    logger.info("command", { name: command.name, actor: ctx.message?.senderId });
    await command.run({ ...ctx, args: parsed.args });
    return { handled: true };
  }
}

module.exports = { CommandRegistry };
