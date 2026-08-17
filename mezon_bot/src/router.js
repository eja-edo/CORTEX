"use strict";

/**
 * Turning an inbound message into an action.
 *
 * The split is: anything starting with the prefix goes to a command;
 * everything else is conversation with the AI. M1 stops at the first half
 * — the conversation path answers with a placeholder until M3 wires the
 * agent stream in. That boundary is drawn here so M3 changes one function
 * and nothing else.
 */

const { logger } = require("./logger");
const { text } = require("./mezon/embed");

// Message scopes this bot answers in. See `MezonGateway._normalise` for
// how a scope is derived, and why `mode` is the only field that can
// decide it.
const SERVED_SCOPES = new Set(["dm"]);

class MessageRouter {
  constructor({ gateway, registry, cortex, prefix }) {
    this.gateway = gateway;
    this.registry = registry;
    this.cortex = cortex;
    this.prefix = prefix;
  }

  /**
   * Who is this, in Cortex terms?
   *
   * A failure to reach the backend is reported as `{ linked: false,
   * error: true }` rather than throwing, so an outage degrades to "I can't
   * check right now" instead of silence. Silence is the one response that
   * looks identical to the bot being dead.
   */
  async _identify(mezonUserId) {
    try {
      const result = await this.cortex.resolveChannel(mezonUserId);
      return { linked: Boolean(result?.linked), userId: result?.user_id ?? null };
    } catch (err) {
      logger.warn("identity lookup failed", { error: err?.message });
      return { linked: false, error: true };
    }
  }

  async handleMessage(message) {
    // M1 serves one-to-one DMs and nothing else, stated as a list rather
    // than as `if (!isDirectMessage) return` so the decision is visible
    // and cheap to widen later.
    //
    // Why not clan channels or groups: a bot that answers every message in
    // a shared space is a bot that gets muted. Serving those well means
    // answering only when mentioned, and deciding whose Cortex account a
    // message in a shared room acts on — a design question of its own, not
    // a default to drift into.
    if (!SERVED_SCOPES.has(message.scope)) {
      logger.debug("ignoring message outside served scope", {
        scope: message.scope,
        mode: message.mode,
        channel_id: message.channelId,
      });
      return;
    }

    const reply = async (content) => {
      const payload = typeof content === "string" ? text(content) : content;
      await this.gateway.sendToChannel(message.channelId, payload);
    };

    const identity = await this._identify(message.senderId);

    if (identity.error) {
      await reply("⚠️ Không kết nối được tới Cortex. Thử lại sau ít phút.");
      return;
    }

    const parsed = this.registry.parse(message.text);
    if (parsed) {
      await this.registry.dispatch(parsed, {
        message,
        identity,
        cortex: this.cortex,
        registry: this.registry,
        prefix: this.prefix,
        reply,
      });
      return;
    }

    await this._handleConversation({ message, identity, reply });
  }

  /** Replaced in M3 by the agent stream + edit-based streaming. */
  async _handleConversation({ identity, reply }) {
    if (!identity.linked) {
      await reply(
        "Chào bạn 👋 Tài khoản Mezon này chưa liên kết với Cortex.\n" +
          `Mở Cortex trên web → Settings → Liên kết Mezon để lấy mã, rồi gõ \`${this.prefix}link <mã>\`.`
      );
      return;
    }
    await reply(
      "Phần trò chuyện với AI đang được hoàn thiện (M3).\n" +
        `Hiện có: \`${this.prefix}help\`, \`${this.prefix}ping\`, \`${this.prefix}link\`.`
    );
  }

  /**
   * Button clicks.
   *
   * Selecting an option in a dropdown fires this same event with the
   * select's own id and a bare, non-JSON `extra_data` — so an unrecognised
   * `button_id` is normal traffic to be ignored, not an error to report.
   * See `interactions.js`.
   */
  async handleButton(event) {
    logger.debug("button", { buttonId: event?.button_id, actor: event?.user_id });
  }
}

module.exports = { MessageRouter };
