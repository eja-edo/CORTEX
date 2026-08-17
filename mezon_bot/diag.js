"use strict";

/**
 * Why is `channel_message` never arriving?
 *
 * The bot connects, reports ready, and then hears nothing — for hours —
 * while the same account and token used to receive messages fine. Three
 * things could produce that, and they need completely different fixes:
 *
 *   A. The socket is not actually open (reconnect loop, silent failure).
 *   B. The socket is open but the bot is not subscribed to the DM channel,
 *      so the server has no reason to send anything.
 *   C. Everything is subscribed and the platform is simply not delivering.
 *
 * This dumps the client's own view of the world after login — clans,
 * channels, DM descriptors, socket state — and then tries an explicit
 * `joinChat` on the DM channel. If messages start flowing only after that
 * call, the answer is B and the fix belongs in the gateway's connect step.
 *
 * Run alone: two processes on one token fight over delivery.
 *   DIAG_DM_CHANNEL_ID=<channel id> node diag.js
 */

require("dotenv").config();
const { MezonClient } = require("mezon-sdk");

const botId = process.env.MEZON_BOT_ID;
const token = process.env.MEZON_BOT_TOKEN;

// A DM channel to test membership against directly, rather than inferring
// it from whether messages happen to arrive. Required rather than
// defaulted: a real channel id baked in here would be one person's id
// committed to the repo forever, and useless to anyone else.
const KNOWN_DM_CHANNEL = process.env.DIAG_DM_CHANNEL_ID;

function line(label, value) {
  console.log(`  ${String(label).padEnd(28)} ${value}`);
}

async function main() {
  if (!botId || !token) {
    console.error("Thiếu MEZON_BOT_ID / MEZON_BOT_TOKEN trong .env");
    process.exit(1);
  }

  if (!KNOWN_DM_CHANNEL) {
    console.error(
      "Thiếu DIAG_DM_CHANNEL_ID.\n" +
        "Lấy channel_id của DM từ bot.log (dòng `inbound`), rồi chạy:\n" +
        "  DIAG_DM_CHANNEL_ID=<id> node diag.js"
    );
    process.exit(1);
  }

  const client = new MezonClient({ botId, token });

  let eventCount = 0;
  const seen = Object.create(null);
  const originalEmit = client.emit.bind(client);
  client.emit = (name, ...args) => {
    const key = String(name);
    seen[key] = (seen[key] ?? 0) + 1;
    if (key !== "ready") {
      eventCount++;
      console.log(
        `\n🔔 EVENT ${key}`,
        JSON.stringify({
          sender_id: args[0]?.sender_id,
          channel_id: args[0]?.channel_id,
          clan_id: args[0]?.clan_id,
          mode: args[0]?.mode,
          text: args[0]?.content?.t,
        })
      );
    }
    return originalEmit(name, ...args);
  };

  console.log("⏳ Đăng nhập...");
  await client.login();
  console.log("✅ Đăng nhập xong\n");

  console.log("── Clans ─────────────────────────────────────────");
  line("clans.size", client.clans?.size ?? "n/a");
  for (const [id, clan] of client.clans?.cache ?? []) {
    line(`  clan ${id}`, `${clan?.name ?? "?"} | channels=${clan?.channels?.size ?? 0}`);
  }
  // Clan "0" is the pseudo-clan every DM lives under. Its absence would
  // explain everything downstream: `_cacheDmChannel` returns early without
  // it, so no DM channel ever enters the cache.
  line("có clan '0' (DM)?", client.clans?.get("0") ? "✅ CÓ" : "❌ KHÔNG");

  console.log("\n── Channels đã cache ─────────────────────────────");
  line("channels.size", client.channels?.size ?? "n/a");
  for (const [id, ch] of client.channels?.cache ?? []) {
    line(`  channel ${id}`, `type=${ch?.channel_type} clan=${ch?.clan?.id}`);
  }
  line(
    `DM ${KNOWN_DM_CHANNEL} có trong cache?`,
    client.channels?.get(KNOWN_DM_CHANNEL) ? "✅ CÓ" : "❌ KHÔNG"
  );

  console.log("\n── DM descriptors (từ API) ───────────────────────");
  const cm = client.channelManager;
  const descs = cm?.getAllDmChannelDescs?.() ?? cm?.allDmChannelDescs ?? [];
  line("số DM channel API trả về", Array.isArray(descs) ? descs.length : "n/a");
  for (const d of Array.isArray(descs) ? descs : []) {
    line(`  ${d.channel_id}`, `type=${d.type} users=${JSON.stringify(d.user_ids)}`);
  }

  console.log("\n── Socket ────────────────────────────────────────");
  const sm = client.socketManager;
  try {
    line("socket.isOpen()", sm?.isOpen?.() ? "✅ mở" : "❌ đóng");
  } catch (err) {
    line("socket.isOpen()", `lỗi: ${err?.message}`);
  }

  // The decisive experiment. `initClanChannelsAndJoin` calls
  // joinClanChat("0", true) for DMs at login; if that is not enough to
  // subscribe to an individual DM channel, joining it explicitly here
  // should make messages start arriving — and that difference is the
  // answer.
  console.log("\n── Thử joinChat thẳng vào DM channel ─────────────");
  try {
    const socket = sm?.getSocket?.();
    if (!socket) {
      line("getSocket()", "❌ không lấy được socket");
    } else {
      // ChannelType.CHANNEL_TYPE_DM = 3, is_public = false.
      const result = await socket.joinChat("0", KNOWN_DM_CHANNEL, 3, false);
      line("joinChat", `✅ ok ${JSON.stringify(result ?? {}).slice(0, 120)}`);
    }
  } catch (err) {
    line("joinChat", `❌ ${err?.message ?? err}`);
  }

  console.log("\n══════════════════════════════════════════════════");
  console.log("Giờ NHẮN cho bot trên Mezon. Mỗi event sẽ in ra ngay.");
  console.log("Bảng đếm in mỗi 30s. Ctrl+C để dừng.");
  console.log("══════════════════════════════════════════════════\n");

  setInterval(() => {
    console.log(`⏱  tally: ${JSON.stringify(seen)} | tổng event (trừ ready): ${eventCount}`);
  }, 30000);
}

main().catch((err) => {
  console.error("FATAL", err?.message, err?.stack);
  process.exit(1);
});
