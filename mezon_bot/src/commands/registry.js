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
 *
 * 3. **A typo gets an answer, not a catalogue.** Someone who typed
 *    `*models` knows what they wanted; sending them to `*help` to re-read
 *    eleven commands makes them do the work of finding the one letter they
 *    got wrong. `suggest()` does that work instead.
 */

const { logger } = require("../logger");

/** Most names offered for one typo. Two is a question ("a hay b?"); three
 *  is a list, and a list is what `*help` already is. */
const MAX_SUGGESTIONS = 2;

/** Below this length a prefix is not evidence of anything — `*t` shares a
 *  prefix with half the registry, and the one-letter alias `h` is a prefix
 *  of every typo starting with an h. Applies to BOTH sides of the
 *  comparison: it is the shorter of the two that decides whether a shared
 *  prefix means anything. Short names still reach the edit-distance rule
 *  below, which is stricter. */
const MIN_PREFIX_LENGTH = 3;

/**
 * The clan-icon form of a command: `:today:`, optionally followed by
 * arguments.
 *
 * Mezon pops up an icon picker the moment someone types `:`, filtered as
 * they keep typing. Naming a clan icon after each command turns that picker
 * into command autocomplete — a thing this bot cannot build for itself,
 * borrowed from the client for free.
 *
 * Anchored at the start on purpose: an icon inside a sentence ("ok :next:
 * nhé") is someone talking, not someone issuing a command.
 */
const EMOJI_COMMAND = /^:([a-z0-9_+-]+):\s*/i;

/**
 * Levenshtein distance. Iterative, two rows — command names are a handful
 * of characters, so the point is not speed but having no dependency for
 * something this small.
 */
function editDistance(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;

  let previous = Array.from({ length: b.length + 1 }, (_, i) => i);
  let current = new Array(b.length + 1);

  for (let i = 1; i <= a.length; i += 1) {
    current[0] = i;
    for (let j = 1; j <= b.length; j += 1) {
      const substitution = previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1);
      current[j] = Math.min(current[j - 1] + 1, previous[j] + 1, substitution);
    }
    [previous, current] = [current, previous];
  }

  return previous[b.length];
}

/**
 * How close `typed` is to one registered name — lower is closer, `null`
 * means "not close enough to offer".
 *
 * Two different kinds of near-miss, deliberately scored on one scale:
 *
 * - **A prefix either way** (`models`/`model`, `inbo`/`inbox`). Scored
 *   below any single edit, because a shared prefix of three or more
 *   characters is a much stronger signal of intent than one substituted
 *   letter somewhere in the middle. Both names must clear the length bar,
 *   or the one-letter alias `h` outranks `help` as the fix for `*halp` —
 *   a suggestion that is technically valid and reads as gibberish.
 * - **A typo** — one edit for short names, two once there is enough name
 *   left for two edits not to mean a different word. Without that scaling,
 *   distance 2 on a four-letter name turns `*ping` into a suggestion for
 *   `*link`, which is not a fix, it is a different command.
 */
function proximity(typed, name) {
  if (
    Math.min(typed.length, name.length) >= MIN_PREFIX_LENGTH &&
    (name.startsWith(typed) || typed.startsWith(name))
  ) {
    return 0.5;
  }

  const threshold = typed.length <= 4 ? 1 : 2;
  const distance = editDistance(typed, name);
  return distance <= threshold ? distance : null;
}

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

    const asIcon = this._parseIconForm(trimmed);
    if (asIcon) return asIcon;

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

  /**
   * `:name:` at the head of a message, but **only when `name` is a command
   * that exists**.
   *
   * That condition is the whole design, not an optimisation. Unlike the
   * `*` prefix — which is a person unambiguously asking to run something —
   * `:x:` is how every ordinary icon is written. `:pepe_joy:` is somebody
   * being cheerful; answering it with "Không có lệnh `:pepe_joy:`. Ý bạn
   * là…?" would be the bot arguing with a smiley. So an unregistered icon
   * returns `null` and the message goes to the AI like any other, and the
   * near-miss suggestions stay on the `*` form where a typo really is a
   * typo.
   */
  _parseIconForm(trimmed) {
    const match = EMOJI_COMMAND.exec(trimmed);
    if (!match) return null;

    const name = match[1].toLowerCase();
    if (!this.commands.has(name)) return null;

    return { name, args: trimmed.slice(match[0].length).trim() };
  }

  /**
   * Registered names closest to what was typed, nearest first, at most
   * `MAX_SUGGESTIONS`.
   *
   * Ranks over every key — aliases included, since an alias is a name a
   * user can legitimately type — but returns each command at most once,
   * under whichever of its names came closest. `switch_model` and its
   * alias `model` are one command; offering both as two separate answers
   * to one typo would be noise dressed as help.
   *
   * Ties break alphabetically so the same typo always gets the same
   * answer. A suggestion that changes between two identical messages
   * reads as the bot guessing.
   */
  suggest(name) {
    const typed = (name ?? "").trim().toLowerCase();
    if (!typed) return [];

    const best = new Map();
    for (const [key, command] of this.commands) {
      const score = proximity(typed, key);
      if (score === null) continue;

      const current = best.get(command);
      if (!current || score < current.score) best.set(command, { key, score });
    }

    return [...best.values()]
      .sort((a, b) => a.score - b.score || a.key.localeCompare(b.key))
      .slice(0, MAX_SUGGESTIONS)
      .map((entry) => entry.key);
  }

  async dispatch(parsed, ctx) {
    const command = this.commands.get(parsed.name);
    if (!command) {
      const suggestions = this.suggest(parsed.name);
      const opening = `Không có lệnh \`${this.prefix}${parsed.name}\`.`;
      // The help pointer stays even when there is a suggestion: a wrong
      // guess otherwise leaves the user with no next move at all.
      const closing = `Gõ \`${this.prefix}help\` để xem tất cả.`;

      if (suggestions.length) {
        const offered = suggestions.map((s) => `\`${this.prefix}${s}\``).join(" hay ");
        await ctx.reply(`${opening} Ý bạn là có phải là ${offered}? ${closing}`);
      } else {
        await ctx.reply(`${opening} ${closing}`);
      }
      return { handled: true, unknown: true, suggestions };
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
