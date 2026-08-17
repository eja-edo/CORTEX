/**
 * M0 — Probe. Not the bot; the experiment that has to happen before the bot.
 *
 * `MessageButtonClicked.extra_data` is typed `string` in the SDK and its
 * contents are documented nowhere. Every form in R1 depends on parsing it,
 * so building R1 first would mean building a parser against a guess. This
 * script exists to replace that guess with an observation.
 *
 * It answers five questions, each mapped to one command:
 *
 *   *probe    → What does `extra_data` actually contain? Every input type
 *               is present exactly once with a distinctive id, so the dump
 *               shows how each one serialises and whether untouched fields
 *               come back at all.
 *   *stream   → Does edit-as-you-go work, and how fast can it go before
 *               the gateway pushes back? (R3 lives or dies on this.)
 *   *dm       → Does sendDM open a DM channel unprompted? (R4 needs to
 *               reach a user who never messaged the bot first.)
 *   *echo     → What does an inbound DM look like — how do we recognise a
 *               DM vs a channel message, and where is the text?
 *   *whoami   → What identifiers does a sender carry, so R2's
 *               mezon_user_id ↔ cortex user_id mapping has something stable
 *               to key on.
 *
 * Everything observed is appended to probe-findings.jsonl. That file is the
 * deliverable of M0 — not this script.
 *
 * Run: cp .env.example .env && edit && npm run probe    (Node 22, see README)
 */

require("dotenv").config();
const fs = require("fs");
const path = require("path");

const {
  MezonClient,
  InteractiveBuilder,
  ButtonBuilder,
  EButtonMessageStyle,
  Events,
} = require("mezon-sdk");

// run.sh sets PROBE_FINDINGS to a per-run timestamped file so consecutive
// attempts do not pile into one stream — comparing round 2 against round 3
// is the whole method here, and that needs them kept apart.
const FINDINGS = path.join(__dirname, process.env.PROBE_FINDINGS || "probe-findings.jsonl");

/** Append one observation. Written per-event rather than at exit so a crash
 *  mid-probe still leaves everything observed up to that point. */
function record(kind, data) {
  const entry = { at: new Date().toISOString(), kind, ...data };
  fs.appendFileSync(FINDINGS, JSON.stringify(entry) + "\n");
  console.log(`\n📌 [${kind}]`);
  console.dir(data, { depth: null, colors: true });
}

/**
 * The whole point of the probe.
 *
 * `extra_data` is a string of unknown shape, so this deliberately does not
 * assume JSON: it records the raw text and the length first, and only then
 * reports what parsing produced. If it turns out not to be JSON, the raw
 * field is what tells us what it is instead — a conclusion that is
 * impossible to reach from a parser that threw the input away.
 */
function dissect(raw) {
  const out = { raw, type: typeof raw, length: raw == null ? null : String(raw).length };
  if (typeof raw !== "string" || raw.length === 0) {
    out.verdict = "not a non-empty string";
    return out;
  }
  try {
    const parsed = JSON.parse(raw);
    out.parsed = parsed;
    out.verdict = "valid JSON";
    out.topLevelType = Array.isArray(parsed) ? "array" : typeof parsed;
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      out.keys = Object.keys(parsed);
      // Per-key types matter as much as the keys: knowing whether a
      // datepicker returns "2026-08-17", an epoch number, or a nested
      // object is the difference between a working parser and a broken one.
      out.valueTypes = Object.fromEntries(
        Object.entries(parsed).map(([k, v]) => [
          k,
          Array.isArray(v) ? `array[${v.length}]` : v === null ? "null" : typeof v,
        ])
      );
    }
  } catch (err) {
    out.verdict = `NOT JSON — ${err.message}`;
  }
  return out;
}

/** One embed carrying every input type the SDK can build, each with a
 *  distinctive id, so a single click reveals how all of them serialise. */
function buildProbeForm() {
  const embed = new InteractiveBuilder("🔬 Probe form — bấm Submit sau khi điền")
    .setDescription(
      "Điền vài ô (cố ý BỎ TRỐNG vài ô khác — cần biết ô trống có quay về không), rồi bấm Submit."
    )
    .addInputField("p_text", "1. Text", "nhập chữ", { defaultValue: "giá trị mặc định" })
    .addInputField("p_textarea", "2. Textarea", "nhiều dòng", { textarea: true })
    .addInputField("p_number", "3. Number", "123", { type: "number" })
    .addSelectField(
      "p_select",
      "4. Select",
      [
        { label: "Lựa chọn A", value: "a" },
        { label: "Lựa chọn B", value: "b" },
      ],
      undefined,
      "một lựa chọn"
    )
    .addRadioField(
      "p_radio",
      "5. Radio (đơn)",
      [
        { label: "Thấp", value: "low" },
        { label: "Cao", value: "high" },
      ],
      "chọn một"
    )
    .addRadioField(
      "p_radio_multi",
      "6. Radio (nhiều)",
      // Each option needs a DISTINCT `name`. The client decides single vs
      // multi with `options[0].name !== options[1].name`
      // (EmbedOptionRatio.tsx) — plain HTML radio-group semantics, where a
      // shared name is exactly what makes options mutually exclusive. The
      // SDK comment "Apply when use mutiple choice" reads like it wants one
      // shared group name and gets this backwards; giving all three the
      // same name silently produced a single-choice control.
      [
        { label: "X", value: "x", name: "m_x" },
        { label: "Y", value: "y", name: "m_y" },
        { label: "Z", value: "z", name: "m_z" },
      ],
      "chọn nhiều",
      3
    )
    .addDatePickerField("p_date", "7. Date", "chọn ngày — cần biết format trả về")
    .build();

  const components = [
    {
      components: new ButtonBuilder()
        .addButton("p_submit", "Submit", EButtonMessageStyle.PRIMARY)
        .addButton("p_cancel", "Cancel", EButtonMessageStyle.SECONDARY)
        .build(),
    },
  ];

  return { embed: [embed], components };
}

/**
 * R3 feasibility: edit one message repeatedly, with the interval shrinking,
 * and time every call. If the gateway throttles or errors, it shows up here
 * as a rising duration or a rejection — before it shows up in production as
 * a chat that stutters.
 */
async function runStreamProbe(message, channel) {
  // Round 1 taught the lesson this version is built around: every update
  // returned an ack in 23–127ms and reported no error, yet the rendered
  // message stopped dead at the 400ms→150ms boundary. **An ack is not
  // proof of a render.** So this round no longer trusts the return value:
  // it walks an interval ladder with a marker per step, then reads the
  // message back from the server and compares. Whatever survives the
  // read-back is what actually landed.
  const steps = [
    { ms: 1000, marks: 2 },
    { ms: 600, marks: 2 },
    { ms: 400, marks: 2 },
    { ms: 250, marks: 2 },
    { ms: 150, marks: 2 },
    { ms: 60, marks: 3 },
  ];

  const timings = [];
  let acc = "Streaming ladder:";
  let n = 0;

  for (const step of steps) {
    for (let i = 0; i < step.marks; i++) {
      n++;
      // Each marker names the interval that produced it, so the final
      // rendered text says out loud where the platform stopped keeping up.
      acc += ` [${n}@${step.ms}ms]`;
      await new Promise((r) => setTimeout(r, step.ms));
      const t0 = Date.now();
      let error = null;
      try {
        await message.update({ t: acc });
      } catch (err) {
        error = err?.message ?? String(err);
      }
      timings.push({ edit: n, intervalMs: step.ms, ackMs: Date.now() - t0, error });
    }
  }

  const lastSent = acc;

  // Settle before the final edit. If the closing edit lands inside a drop
  // window the user is left with a permanently truncated message — the
  // worst failure mode for R3, because nothing reports it.
  await new Promise((r) => setTimeout(r, 1500));
  const finalText = lastSent + "\n\n✅ Xong.";
  await message.update({ t: finalText });
  await new Promise((r) => setTimeout(r, 1500));

  // The actual measurement: what does the *server* hold now?
  //
  // The cache entry has to be evicted first. `CacheManager.fetch` returns
  // a cached value when there is one, and `Message.update` writes what it
  // sent straight back into that cache — so reading without evicting would
  // compare our own copy against itself and always agree, which is exactly
  // the false negative this probe exists to avoid.
  let readBack = null;
  let readBackError = null;
  try {
    channel.messages.delete(message.id);
    const fetched = await channel.messages.fetch(message.id);
    readBack = fetched?.content?.t ?? null;
  } catch (err) {
    readBackError = err?.message ?? String(err);
  }

  record("stream_probe", {
    editsAttempted: n,
    allAcked: timings.every((t) => !t.error),
    timings,
    lastSentLength: lastSent.length,
    finalSentLength: finalText.length,
    readBack,
    readBackLength: readBack?.length ?? null,
    readBackError,
    readBackMatchesFinal: readBack === finalText,
    note:
      "readBackMatchesFinal=false ⇒ ack đã trả về nhưng nội dung KHÔNG lưu. " +
      "Marker cuối cùng còn sót trong readBack cho biết nhịp edit an toàn.",
  });
}

async function main() {
  const botId = process.env.MEZON_BOT_ID;
  const token = process.env.MEZON_BOT_TOKEN;

  if (!botId || !token) {
    console.error(
      "❌ Thiếu MEZON_BOT_ID hoặc MEZON_BOT_TOKEN.\n" +
        "   cp .env.example .env rồi điền — xem README.md.\n" +
        "   (botId là BẮT BUỘC: SDK ném 'botId is required' ngay ở constructor,\n" +
        "    ví dụ new MezonClient({ token }) trong docs Mezon là thiếu.)"
    );
    process.exit(1);
  }

  const client = new MezonClient({ botId, token });

  // ── Diagnostic tap ────────────────────────────────────────────────────
  // Round 2 produced a contradiction: button clicks arrived while inbound
  // messages did not, from the same live socket. Guessing why would be the
  // exact mistake M0 exists to prevent, so this wraps `emit` and records
  // every event name the client raises. If `channel_message` never appears
  // here, the message is not reaching the SDK at all and the problem is
  // subscription-side; if it appears and the handler still does not run,
  // the problem is ours.
  const seenEvents = Object.create(null);
  const originalEmit = client.emit.bind(client);
  client.emit = (eventName, ...args) => {
    const key = String(eventName);
    seenEvents[key] = (seenEvents[key] ?? 0) + 1;
    if (key !== "ready") {
      record("raw_event", {
        event: key,
        firstArgKeys:
          args[0] && typeof args[0] === "object" ? Object.keys(args[0]).slice(0, 25) : typeof args[0],
        channel_id: args[0]?.channel_id,
        clan_id: args[0]?.clan_id,
        sender_id: args[0]?.sender_id,
        text: args[0]?.content?.t,
      });
    }
    return originalEmit(eventName, ...args);
  };

  // Periodic tally, so a quiet socket is distinguishable from a dead one.
  setInterval(() => {
    record("event_tally", { seenEvents, note: "đếm dồn mọi event kể từ lúc khởi động" });
  }, 60_000).unref?.();

  client.on("ready", () => {
    record("ready", {
      botId,
      clanCount: client.clans?.size ?? null,
      note: "đăng nhập ok — DM cho bot: *probe | *stream | *dm | *echo | *whoami",
    });
  });

  client.onChannelMessage(async (message) => {
    // The bot sees its own messages too; without this the *echo probe
    // answers itself in a loop.
    if (message.sender_id === botId) return;

    const text = message.content?.t ?? "";

    record("inbound_message", {
      text,
      sender_id: message.sender_id,
      username: message.username,
      display_name: message.display_name,
      channel_id: message.channel_id,
      clan_id: message.clan_id,
      mode: message.mode,
      code: message.code,
      is_public: message.is_public,
      // clan_id "0" is how sendDM tags a DM on the way out, so it is the
      // most likely inbound marker too — but "likely" is what this probe
      // exists to replace.
      guess_is_dm: message.clan_id === "0" || message.clan_id === undefined,
      contentKeys: Object.keys(message.content ?? {}),
    });

    const cmd = text.trim().split(/\s+/)[0];

    try {
      const channel = await client.channels.fetch(message.channel_id);

      if (cmd === "*probe") {
        const { embed, components } = buildProbeForm();
        const sent = await channel.send({ t: "", embed, components });
        record("probe_form_sent", {
          message_id: sent?.id ?? null,
          note: "điền form rồi bấm Submit — chờ sự kiện button_clicked",
        });
        return;
      }

      if (cmd === "*stream") {
        const sent = await channel.send({ t: "Streaming ladder:" });
        await runStreamProbe(sent, channel);
        return;
      }

      if (cmd === "*dm") {
        // R4 depends on reaching a user who has not messaged the bot, so
        // the interesting case is the DM channel not existing yet.
        // NOT `dmClan.users.fetch(...)` — the Mezon docs show that and it
        // throws: `Clan` exposes only `channels`, never `users`. The user
        // cache lives on the client (MezonClientCore.users).
        const user = await client.users.fetch(message.sender_id);
        const before = user.dmChannelId;
        const sent = await user.sendDM({ t: "📬 DM thử từ bot (probe *dm)" });
        record("dm_probe", {
          dmChannelId_before: before || "(rỗng — chưa có channel)",
          dmChannelId_after: user.dmChannelId,
          sent_message_id: sent?.id ?? null,
          same_as_current_channel: user.dmChannelId === message.channel_id,
        });
        return;
      }

      if (cmd === "*whoami") {
        // NOT `dmClan.users.fetch(...)` — the Mezon docs show that and it
        // throws: `Clan` exposes only `channels`, never `users`. The user
        // cache lives on the client (MezonClientCore.users).
        const user = await client.users.fetch(message.sender_id);
        record("whoami", {
          id: user.id,
          username: user.username,
          display_name: user.display_name,
          dmChannelId: user.dmChannelId,
          note: "trường nào ổn định thì dùng làm user_channels.address",
        });
        await channel.send({ t: `id=\`${user.id}\` username=\`${user.username}\`` });
        return;
      }

      if (cmd === "*echo") {
        await channel.send({ t: `echo: ${text.slice(6)}` });
        return;
      }

      await channel.send({
        t: "Probe commands: `*probe` `*stream` `*dm` `*echo <text>` `*whoami`",
      });
    } catch (err) {
      record("handler_error", { cmd, error: err?.message ?? String(err), stack: err?.stack });
    }
  });

  // ── The finding M0 exists for ──────────────────────────────────────────
  client.onMessageButtonClicked(async (event) => {
    record("button_clicked", {
      button_id: event.button_id,
      message_id: event.message_id,
      channel_id: event.channel_id,
      sender_id: event.sender_id,
      user_id: event.user_id,
      // sender_id vs user_id: one of them is the clicker and one is the
      // message author. Which is which decides whether a bot can trust a
      // click, so it is recorded rather than assumed.
      sender_equals_user: event.sender_id === event.user_id,
      extra_data: dissect(event.extra_data),
      allEventKeys: Object.keys(event),
    });

    try {
      const channel = await client.channels.fetch(event.channel_id);
      await channel.send({
        t: `✅ Nhận button \`${event.button_id}\`. extra_data đã ghi vào probe-findings.jsonl`,
      });
    } catch (err) {
      record("button_ack_error", { error: err?.message ?? String(err) });
    }
  });

  client.onDropdownBoxSelected(async (event) => {
    record("dropdown_selected", {
      selectbox_id: event.selectbox_id,
      message_id: event.message_id,
      values: event.values,
      sender_id: event.sender_id,
      user_id: event.user_id,
      note: "select bắn event riêng hay chỉ gộp vào extra_data lúc submit?",
    });
  });

  console.log("⏳ Đang đăng nhập Mezon...");
  await client.login();
  console.log("✅ Đã đăng nhập. DM cho bot: *probe");
}

// `buildProbeForm` and `dissect` are the two pure parts, exported so
// dry-run.js can exercise them without credentials — the payload being
// well-formed is checkable on a laptop; only what comes *back* needs a
// live gateway.
module.exports = { buildProbeForm, dissect };

if (require.main === module) {
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => {
      console.log(`\n👋 ${sig} — findings: ${FINDINGS}`);
      process.exit(0);
    });
  }

  main().catch((err) => {
    record("fatal", { error: err?.message ?? String(err), stack: err?.stack });
    process.exit(1);
  });
}
