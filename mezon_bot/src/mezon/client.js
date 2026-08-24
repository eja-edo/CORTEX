"use strict";

/**
 * The seam between this bot and `mezon-sdk`.
 *
 * Nothing outside this file imports the SDK except `embed.js`. Two reasons,
 * both already demonstrated rather than hypothetical: the published docs
 * disagree with the shipped code in at least three places (`botId` is
 * mandatory, `Clan` has no `users`, `createDmChannel` is private), and the
 * multi-select rule lives in the *web client*, not the SDK. A library
 * documented that loosely will move; when it does, it should move inside
 * one file.
 */

const { MezonClient } = require("mezon-sdk");
const { config } = require("../config");
const { logger } = require("../logger");

// ChannelType.CHANNEL_TYPE_DM. Inlined rather than imported because the
// numeric value is wire protocol — a rename inside the SDK should not
// silently change which channel type we ask to join.
const CHANNEL_TYPE_DM = 3;

// ChannelStreamMode — where a message was written. This is the *only*
// reliable discriminator: clan_id is "0" for both DMs and group chats, so
// using it to detect a DM silently sweeps groups in with them.
const STREAM_MODE_DM = 4;
const SCOPE_BY_MODE = {
  2: "channel", // a text channel inside a clan
  3: "group", // multi-person chat, no clan
  4: "dm", // one-to-one
  5: "clan",
  6: "thread",
};

class MezonGateway {
  constructor() {
    this.client = null;
    this.botId = config.mezon.botId;
    this.eventCounts = Object.create(null);
    this._tallyTimer = null;
  }

  async connect() {
    this.client = new MezonClient({
      botId: config.mezon.botId,
      token: config.mezon.token,
    });
    this._installEventTap();
    await this.client.login();
    logger.info("Mezon connected", { botId: this.botId, clans: this.client.clans?.size ?? 0 });
    await this._joinDmChannels();
    return this;
  }

  /**
   * Subscribe explicitly to every DM channel.
   *
   * Login already calls `joinClanChat("0", true)` for the DM pseudo-clan,
   * and for a bot that belongs to no real clan that appears to be enough.
   * It stopped being enough once this bot was added to a second clan:
   * from then on `message_button_clicked` kept arriving while
   * `channel_message` never did — six button events and zero messages in
   * one observed run. Button clicks are routed to the author of the
   * message holding the button, so they do not depend on channel
   * membership; text messages do. That difference is what points at
   * subscription rather than at the socket, which was demonstrably open
   * the whole time.
   *
   * Joining a channel already joined is harmless, so this runs on every
   * connect rather than trying to detect whether it is needed — a check
   * that would itself have to guess at the condition it is checking for.
   *
   * Failures are logged, never fatal: one unreachable DM channel must not
   * stop the bot from serving the others.
   */
  async _joinDmChannels() {
    const socket = this.client.socketManager?.getSocket?.();
    const descriptors = this.client.channelManager?.getAllDmChannelDescs?.() ?? [];

    if (!socket) {
      logger.warn("no socket available to join DM channels");
      return;
    }

    let joined = 0;
    for (const descriptor of descriptors) {
      if (!descriptor?.channel_id) continue;
      try {
        await socket.joinChat("0", descriptor.channel_id, CHANNEL_TYPE_DM, false);
        joined++;
      } catch (err) {
        logger.warn("joinChat failed for DM channel", {
          channel_id: descriptor.channel_id,
          error: err?.message ?? String(err),
        });
      }
    }

    logger.info("DM channels joined", { joined, total: descriptors.length });
    if (descriptors.length === 0) {
      // Nobody has ever DMed the bot, or the descriptor fetch failed. The
      // first case is normal for a fresh bot; the second is worth seeing.
      logger.warn("no DM channels returned by the API — bot will not receive DMs");
    }
  }

  /**
   * Count every event the SDK raises, and log a tally periodically.
   *
   * This is not debug scaffolding to remove later. "The bot isn't
   * responding" has already meant three different things during this
   * project — a stale web client delivering nothing, a second process
   * stealing the socket, and a handler throwing — and from the outside all
   * three look identical. The tally is what separates them: no
   * `channel_message` at all means the message never reached us, while
   * events arriving with no reply means the fault is ours.
   *
   * Wrapping `emit` rather than subscribing to each event name is
   * deliberate: a subscriber only sees the events it knows to ask for, and
   * the interesting case is the event you did not expect.
   */
  _installEventTap() {
    const originalEmit = this.client.emit.bind(this.client);
    this.client.emit = (eventName, ...args) => {
      const key = String(eventName);
      this.eventCounts[key] = (this.eventCounts[key] ?? 0) + 1;
      logger.debug("mezon event", {
        event: key,
        sender_id: args[0]?.sender_id,
        channel_id: args[0]?.channel_id,
        clan_id: args[0]?.clan_id,
        mode: args[0]?.mode,
        text: args[0]?.content?.t,
      });
      return originalEmit(eventName, ...args);
    };

    this._tallyTimer = setInterval(() => {
      logger.info("mezon event tally", this.eventCounts);
    }, 60_000);
    this._tallyTimer.unref?.();
  }

  async close() {
    if (this._tallyTimer) clearInterval(this._tallyTimer);
    try {
      await this.client?.closeSocket();
    } catch (err) {
      logger.warn("closeSocket failed", { error: err?.message });
    }
  }

  /**
   * Inbound user messages, already filtered.
   *
   * The bot receives its own sends and edits back on the same stream — the
   * probe logged 22 raw `channel_message` events for 3 real user messages.
   * Without this filter an echo-style command answers itself forever, so
   * the filter lives here rather than in each handler.
   */
  onUserMessage(handler) {
    this.client.onChannelMessage(async (message) => {
      if (!message) return;
      // Logged before the self-filter on purpose: a message dropped here
      // is indistinguishable from one that never arrived unless we say so.
      if (message.sender_id === this.botId) {
        logger.debug("skipping own message", { channel_id: message.channel_id });
        return;
      }
      logger.info("inbound", {
        sender_id: message.sender_id,
        channel_id: message.channel_id,
        mode: message.mode,
        scope: SCOPE_BY_MODE[message.mode] ?? "unknown",
        clan_id: message.clan_id,
        text: message.content?.t,
      });
      try {
        await handler(this._normalise(message));
      } catch (err) {
        logger.error("message handler threw", { error: err?.message, stack: err?.stack });
      }
    });
    return this;
  }

  onButtonClicked(handler) {
    this.client.onMessageButtonClicked(async (event) => {
      try {
        await handler(event);
      } catch (err) {
        logger.error("button handler threw", { error: err?.message, stack: err?.stack });
      }
    });
    return this;
  }

  /**
   * Where did this message come from?
   *
   * `mode` is the only field that answers this, and it must be the only
   * one consulted. An earlier version also accepted `clan_id === "0"` as
   * "this is a DM", which is wrong in a way that only shows up once the
   * bot is popular: **group chats also live outside any clan**, so
   * `clan_id === "0"` is true for them too. A bot that treats a group as a
   * DM answers every message in it — the fastest route to being muted.
   *
   * A missing `mode` yields `unknown` rather than a guess. Everything
   * observed on live traffic carried one; if that ever changes, the router
   * logs the unknown scope instead of quietly mishandling it.
   */
  _normalise(message) {
    return {
      text: message.content?.t ?? "",
      senderId: message.sender_id,
      username: message.username,
      displayName: message.display_name,
      channelId: message.channel_id,
      clanId: message.clan_id,
      mode: message.mode,
      scope: SCOPE_BY_MODE[message.mode] ?? "unknown",
      isDirectMessage: message.mode === STREAM_MODE_DM,
      raw: message,
    };
  }

  /** `attachments` (images from `toMezonContent`, F2/M3) is the SDK's own
   *  third argument to `channel.send` — not a field on `content` — see
   *  `mezon/markdown.js`'s docstring for why the two can't be merged. */
  async sendToChannel(channelId, content, attachments) {
    const channel = await this.client.channels.fetch(channelId);
    return channel.send(content, undefined, attachments);
  }

  /**
   * DM a user who may never have messaged the bot — the case notification
   * delivery depends on.
   *
   * `client.users.fetch`, **not** `clan.users.fetch`: `Clan` exposes only
   * `channels`, so the docs' example throws. `sendDM` opens the DM channel
   * itself when there isn't one; `createDmChannel` is private and cannot
   * be called from here.
   */
  async sendDirectMessage(mezonUserId, content, attachments) {
    const user = await this.client.users.fetch(mezonUserId);
    return user.sendDM(content, undefined, attachments);
  }

  /** Editing a live message is how streaming is faked (R3). The probe
   *  confirmed the server stores edits reliably down to 60ms intervals;
   *  the throttling that matters is in the caller, not here. `attachments`
   *  — see `sendToChannel`'s note. */
  async editMessage(channelId, messageId, content, attachments) {
    const channel = await this.client.channels.fetch(channelId);
    const message = await channel.messages.fetch(messageId);
    return message.update(content, undefined, attachments);
  }

  /**
   * Remove a message the bot sent.
   *
   * Used for one thing: the thinking transcript, when the bot is
   * configured to hide it once a turn ends (`BOT_KEEP_THINKING=false`).
   * An edit cannot express "this was never worth a message" — the web
   * genuinely unmounts its timeline — and leaving a hollowed-out message
   * behind is a worse artefact than the transcript itself.
   */
  async deleteMessage(channelId, messageId) {
    const channel = await this.client.channels.fetch(channelId);
    const message = await channel.messages.fetch(messageId);
    return message.delete();
  }
}

module.exports = { MezonGateway };
