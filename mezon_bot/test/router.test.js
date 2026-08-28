"use strict";

/**
 * Tests for `MessageRouter._handleConversation` (F2/M3 — R2 "DM thường →
 * AI" + R3 "giả-realtime bằng message.update"). No SDK, no HTTP: `cortex`
 * and `gateway` are hand-built fakes, same convention as `registry.test.js`
 * and `server.test.js`. `StreamThrottle` itself is tested separately in
 * `streamThrottle.test.js` — these tests are about wiring, not timing, so
 * the throttle here is exercised with default timers still running but
 * each test either waits for `streamChat` to fully resolve (which calls
 * `onEvent` synchronously in these fakes, but the throttle's own async
 * edit scheduling still needs a tick) or asserts only on the post-`flush`
 * final state.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MessageRouter } = require("../src/router");
const { CommandRegistry } = require("../src/commands/registry");
const { testCommand } = require("../src/commands/test");

// A hand-built fake, same convention as `cortex`/`gateway` below — never
// hits real MinIO, since these are unit tests of wiring, not of the
// network. `*test svg`'s own upload behaviour is exercised for real
// against MinIO's client library in `test/storage.test.js`.
const fakeStorage = {
  uploadPublicObject: async (buffer, { key }) => `https://fake-minio.test/cortex-recordings/bot-tables/${key}`,
};

function makeRouter({ cortex, storage = fakeStorage, keepThinking } = {}) {
  const sent = [];
  const edits = [];
  const deleted = [];
  let nextId = 1;
  const gateway = {
    sendToChannel: async (channelId, content, attachments) => {
      const id = `msg-${nextId++}`;
      sent.push({ channelId, content, attachments, id });
      return { id };
    },
    editMessage: async (channelId, messageId, content, attachments) => {
      edits.push({ channelId, messageId, content, attachments });
      return { id: messageId };
    },
    deleteMessage: async (channelId, messageId) => {
      deleted.push(messageId);
      return { id: messageId };
    },
  };
  const registry = new CommandRegistry({ prefix: "*" }).register(testCommand);
  const router = new MessageRouter({ gateway, registry, cortex, storage, prefix: "*", keepThinking });
  return { router, sent, edits, deleted };
}

function wait(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

/** The content of the most recent edit, which for a single-message turn
 *  is exactly what the user is looking at right now. */
function lastEditText(edits) {
  return edits[edits.length - 1]?.content.t ?? "";
}

/** What one particular message says now — a turn with reasoning spans
 *  two of them (transcript above, answer below), so "the last edit" is
 *  no longer enough to identify either. */
function textOf(messageId, { sent, edits }) {
  const lastEdit = edits.filter((e) => e.messageId === messageId).at(-1);
  if (lastEdit) return lastEdit.content.t ?? "";
  return sent.find((m) => m.id === messageId)?.content?.t ?? "";
}

function baseMessage(overrides = {}) {
  return {
    text: "chào bạn",
    senderId: "mezon-u1",
    channelId: "ch-1",
    scope: "dm",
    mode: 4,
    ...overrides,
  };
}

test("an unlinked account gets the link prompt, never reaches the agent", async () => {
  let called = false;
  const cortex = {
    resolveChannel: async () => ({ linked: false }),
    streamChat: async () => { called = true; },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(called, false, "must not call the agent for an unlinked account");
  assert.equal(sent.length, 1);
  assert.equal(edits.length, 0);
  assert.match(sent[0].content.t, /chưa liên kết/);
});

test("a linked account gets a placeholder immediately, then the final answer via edit", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ userId, message, timeoutMs, onEvent }) => {
      assert.equal(userId, "cortex-u1");
      assert.equal(message, "chào bạn");
      // Decoupled from the general (short) Cortex client timeout — a real
      // agent turn can go quiet for a while mid-stream with no bug
      // involved (see AGENT_STREAM_IDLE_TIMEOUT_MS's docstring).
      assert.ok(timeoutMs >= 10 * 60 * 1000, "must use a generous idle timeout, not the default few-second one");
      onEvent({ event: "token", text: "Xin " });
      onEvent({ event: "token", text: "chào!" });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(sent.length, 1, "exactly one new message: the placeholder");
  assert.equal(sent[0].content.t, "⏳ đang nghĩ…");
  assert.ok(edits.length >= 1, "the placeholder must be edited at least once (the final flush)");
  const lastEdit = edits[edits.length - 1];
  assert.equal(lastEdit.messageId, sent[0].id);
  assert.equal(lastEdit.content.t, "Xin chào!");
});

test("an answer past one message's character budget overflows into a second Mezon message, not a thrown error", async () => {
  // 45 short paragraphs, well past splitMezonContent's default budget —
  // see markdown.test.js for the split logic itself; this is only about
  // _syncMultiMessage turning "2 chunks" into "placeholder edited with
  // the first, a genuinely new message sent for the second", not
  // corrupting or dropping content along the way. Everything arrives in
  // one `onEvent` + `flush()` here, so the second message gets its final
  // content straight from `sendToChannel` — no follow-up edit needed for
  // it in this scenario, only the first (placeholder) message is edited.
  const paragraphs = Array.from(
    { length: 45 },
    (_, i) => `Đây là đoạn số ${i} với đủ nội dung để tổng độ dài vượt quá giới hạn một tin nhắn.`
  );
  const longAnswer = paragraphs.join("\n\n");

  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: longAnswer });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(sent.length, 2, "the placeholder plus exactly one overflow message");
  const [placeholder, overflow] = sent;
  assert.notEqual(overflow.id, placeholder.id, "the overflow chunk must land in a genuinely new message, not reuse the placeholder's id");
  assert.ok(edits.some((e) => e.messageId === placeholder.id), "the placeholder must be edited away from '⏳ đang nghĩ…' to the first chunk");

  const finalPlaceholderText = edits.filter((e) => e.messageId === placeholder.id).at(-1)?.content.t ?? "";
  const combinedText = `${finalPlaceholderText}\n\n${overflow.content.t}`;
  for (const p of paragraphs) {
    assert.ok(combinedText.includes(p), `paragraph must survive somewhere: "${p}"`);
  }
});

test("_syncMultiMessage edits the first message with its real content the tick it first crosses into a second chunk (regression: it used to skip that edit entirely)", async () => {
  // The bug this pins: a first version treated "a message already
  // exists at this index" as "this chunk is already final" — which
  // skipped editing the placeholder away from "⏳ đang nghĩ…" the very
  // first time the buffer grew past one message, because a message
  // (the placeholder) already existed at index 0, even though it had
  // never actually been edited with real content yet.
  const { router, sent, edits } = makeRouter({ cortex: {} });
  const messageIds = ["placeholder-id"];
  sent.push({ id: "placeholder-id" }); // pre-seed, matching what a real placeholder send would have recorded
  const state = { settledCount: 0 };

  const paragraph = (i) => `Đoạn ${i}: nội dung ngắn gọn để đo độ dài, đủ dài để cần cắt.`;

  const under = Array.from({ length: 40 }, (_, i) => paragraph(i)).join("\n\n");
  await router._syncMultiMessage("ch-1", messageIds, under, state);
  assert.equal(edits.length, 1, "still one chunk — must edit the placeholder with real content, not skip it");
  assert.equal(edits[0].messageId, "placeholder-id");
  assert.notEqual(edits[0].content.t, "⏳ đang nghĩ…");

  const past = Array.from({ length: 60 }, (_, i) => paragraph(i)).join("\n\n");
  await router._syncMultiMessage("ch-1", messageIds, past, state);
  assert.equal(messageIds.length, 2, "the second chunk must create a genuinely new message");
  assert.equal(state.settledCount, 1, "the first chunk is now sealed — it must never be edited again");

  const editsForPlaceholderAfterSettling = edits.filter((e) => e.messageId === "placeholder-id").length;

  const evenMore = `${past}\n\nMột đoạn nữa được thêm vào cuối, chỉ nối dài chunk thứ hai.`;
  await router._syncMultiMessage("ch-1", messageIds, evenMore, state);
  assert.equal(
    edits.filter((e) => e.messageId === "placeholder-id").length,
    editsForPlaceholderAfterSettling,
    "a sealed chunk must not be re-edited on a later tick, even as the buffer keeps growing"
  );
});

test("thinking claims the placeholder and the answer opens its own message below it", async () => {
  // Message order in a channel is send order, so this is the only moment
  // at which thoughts can end up above the answer, the way the web lays
  // them out. Models reason before they answer, so this is the ordinary
  // case rather than a special one.
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "reasoning_token", text: "Cần đếm lịch tuần này." });
      onEvent({ event: "token", text: "Bạn có 4 lịch." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(sent.length, 2, "the placeholder, plus one new message for the answer");
  const [placeholder, answer] = sent;
  assert.match(textOf(placeholder.id, { sent, edits }), /🧠/, "the placeholder becomes the transcript");
  assert.equal(textOf(answer.id, { sent, edits }), "Bạn có 4 lịch.", "and the answer is a message of its own, below");
});

test("a turn with no reasoning at all still uses one message — the placeholder simply stays the answer", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Chào bạn." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(sent.length, 1, "no transcript means no second message");
  assert.equal(textOf(sent[0].id, { sent, edits }), "Chào bạn.");
});

test("a reasoning segment is shown whole, even after a tool call settles it", async () => {
  // The bug this pins: a settled segment used to collapse to its opening
  // line cut at 110 characters, so a turn that reasoned, called a tool,
  // and answered showed one truncated sentence where the web showed
  // paragraphs. Sharing a message with the answer was what forced that
  // cap; with its own message there is nothing to trade against.
  const longThought =
    "The user has provided answers to the three questions asked via ask_user_choice. " +
    "I need to check their existing schedule before proposing anything, because a plan " +
    "that collides with what is already booked is worse than no plan at all.";
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "reasoning_token", text: longThought });
      onEvent({ event: "tool_start", tool_name: "get_schedules" });
      onEvent({ event: "tool_result", tool_name: "get_schedules", success: true });
      onEvent({ event: "reasoning_token", text: "Giờ đã có dữ liệu, tóm tắt lại." });
      onEvent({ event: "token", text: "Tuần này bạn rảnh thứ 5." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  const transcript = textOf(sent[0].id, { sent, edits });
  assert.ok(transcript.includes(longThought), "the settled segment must survive in full, not as its first line");
  assert.match(transcript, /🔧 `get_schedules`/);
  assert.match(transcript, /✅ `get_schedules`/);
  assert.match(transcript, /Giờ đã có dữ liệu/, "and reasoning after the tool call is its own segment");
});

test("with keepThinking on (the default), the transcript stays and stops saying it is still thinking", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "reasoning_token", text: "Cần đếm ghi chú." });
      onEvent({ event: "token", text: "Bạn có 4 ghi chú." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits, deleted } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  const transcript = textOf(sent[0].id, { sent, edits });
  assert.deepEqual(deleted, [], "kept means kept");
  assert.match(transcript, /🧠 \*\*Đã suy nghĩ\*\*/, "in its finished form");
  assert.ok(!transcript.includes("Đang suy nghĩ"), "a transcript that outlives the turn must not claim work is in progress");
});

test("with keepThinking off, the transcript message is deleted — an edited-away husk is a worse artefact than the transcript", async () => {
  // The web unmounts its timeline the moment the turn stops loading;
  // editing a message to some placeholder text cannot express that.
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "reasoning_token", text: "Nghĩ một lúc." });
      onEvent({ event: "token", text: "Xong rồi." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits, deleted } = makeRouter({ cortex, keepThinking: false });

  await router.handleMessage(baseMessage());

  assert.deepEqual(deleted, [sent[0].id], "the transcript message, and only it");
  assert.equal(textOf(sent[1].id, { sent, edits }), "Xong rồi.", "the answer is untouched by any of this");
});

test("tool steps land in the transcript immediately, not on the throttle's next tick", async () => {
  let midStream = null;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "tool_start", tool_name: "search_notes", tool_args: { query: "họp" } });
      onEvent({ event: "tool_result", tool_name: "search_notes", result: { notes: [1, 2, 3] }, success: true });
      await wait(10);
      midStream = lastEditText(edits);
      onEvent({ event: "token", text: "Tìm thấy 3 ghi chú." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.match(midStream ?? "", /🔧 `search_notes` → tìm "họp"/, "the call must be visible as it happens");
  assert.match(midStream ?? "", /✅ `search_notes` · 3 kết quả/, "and so must its result");
  assert.equal(textOf(sent[1].id, { sent, edits }), "Tìm thấy 3 ghi chú.", "none of it leaks into the answer");
});

test("a stream that fails mid-thinking settles the transcript instead of leaving it mid-sentence", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "reasoning_token", text: "Đang cân nhắc các lựa chọn." });
      onEvent({ event: "token", text: "Câu trả lời dở dang" });
      throw new Error("Cortex im lặng quá 30000ms giữa chừng stream");
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleMessage(baseMessage()));

  const transcript = textOf(sent[0].id, { sent, edits });
  assert.ok(!transcript.includes("Đang suy nghĩ"), "the bot has given up; the transcript must not say otherwise");

  const answer = textOf(sent[1].id, { sent, edits });
  assert.match(answer, /Câu trả lời dở dang/, "the partial answer must survive");
  assert.match(answer, /ngắt giữa chừng/);
});

test("a stream failure edits the placeholder into a friendly error, not a thrown error", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async () => {
      throw new Error("Cortex timeout sau 30000ms");
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleMessage(baseMessage()));

  assert.equal(sent.length, 1);
  assert.equal(edits.length, 1);
  assert.equal(edits[0].messageId, sent[0].id);
  assert.match(edits[0].content.t, /sự cố/);
});

test("streamChat throwing after tokens already arrived keeps the partial answer instead of replacing it", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Đây là phần đã trả lời được" });
      throw new Error("Cortex im lặng quá 30000ms giữa chừng stream");
    },
  };
  const { router, edits } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleMessage(baseMessage()));

  const lastEdit = edits[edits.length - 1];
  assert.match(lastEdit.content.t, /Đây là phần đã trả lời được/, "must keep the partial text");
  assert.match(lastEdit.content.t, /ngắt giữa chừng/, "must note that it was cut off");
});

test("an error event mid-stream keeps the buffered text and shows the reason", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Đang" });
      onEvent({ event: "error", message: "model exhausted" });
    },
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  const lastEdit = edits[edits.length - 1];
  // Both halves matter. The partial answer is real and must survive; the
  // reason must reach the user rather than only the log, which is where it
  // used to stop — an `error` event ends the stream normally, so the
  // router's catch block never sees it.
  assert.match(lastEdit.content.t, /^Đang/, "must keep the partial text");
  assert.match(lastEdit.content.t, /model exhausted/, "must show why it stopped");
});

test("an empty token stream still edits the placeholder into something, not left hanging", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async () => {},
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.equal(edits.length, 1);
  assert.equal(edits[0].content.t, "…");
});

test("markdown in the AI's answer (including image syntax) reaches editMessage completely unmodified", async () => {
  // mezon/markdown.js does no processing at all now — see its file
  // docstring for why. The AI's own "![alt](url)" text is not extracted
  // into a separate attachment; it goes through exactly as written.
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Đây là biểu đồ: ![biểu đồ](https://example.com/chart.png)" });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  const lastEdit = edits[edits.length - 1];
  assert.equal(lastEdit.content.t, "Đây là biểu đồ: ![biểu đồ](https://example.com/chart.png)");
  assert.equal(lastEdit.attachments, undefined, "no attachment is extracted — the markdown itself is the whole message");
});

test("no message id back from the send is logged and does not throw", async () => {
  const cortex = { resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }) };
  const { router } = makeRouter({ cortex });
  router.gateway.sendToChannel = async () => ({}); // no `.id`

  await assert.doesNotReject(router.handleMessage(baseMessage()));
});

test("*test needs no link and no Cortex call, and sends the sample verbatim — no markdown processing at all", async () => {
  // See commands/test.js's SAMPLE_MARKDOWN and mezon/markdown.js's file
  // docstring: this bot no longer translates the AI's Markdown into
  // Mezon's own styling — it forwards the text exactly as written.
  let cortexCalled = false;
  const cortex = {
    resolveChannel: async () => ({ linked: false }), // deliberately unlinked
    streamChat: async () => { cortexCalled = true; },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(baseMessage({ text: "*test" }));

  assert.equal(cortexCalled, false, "a pure local-rendering command must never touch Cortex");
  assert.equal(sent.length, 1, "the sample is under the character budget, so it goes out as one message");
  assert.match(sent[0].content.t, /^### Các ví dụ cú pháp Markdown/, "the raw markdown, including its leading #, must survive untouched");
  assert.match(sent[0].content.t, /\| Cú pháp \| Kết quả \|/, "raw table syntax must appear literally, not converted to an embed");
  assert.equal(sent[0].content.mk, undefined, "no mk styling — nothing in this file generates any anymore");
  assert.equal(sent[0].content.embed, undefined, "no embed — tables are no longer extracted into one");
});

test("*test svg uploads the rasterised PNG to storage and sends the returned URL, not a data: URI", async () => {
  // Raw SVG came through as a downloadable file (fixed by rasterising to
  // PNG), and the PNG as a data: URI disconnected the socket (too large
  // for the Mezon gateway) — see commands/test.js's docstring. This
  // confirms the wiring goes through `storage.uploadPublicObject`, not
  // that upload's own behaviour (see test/storage.test.js for that).
  const uploads = [];
  const storage = {
    uploadPublicObject: async (buffer, opts) => {
      uploads.push({ buffer, opts });
      return "https://fake-minio.test/cortex-recordings/bot-tables/table.png";
    },
  };
  const { router, sent } = makeRouter({ cortex: { resolveChannel: async () => ({ linked: false }) }, storage });

  await router.handleMessage(baseMessage({ text: "*test svg" }));

  assert.equal(uploads.length, 1, "must upload exactly once");
  assert.equal(uploads[0].opts.contentType, "image/png");
  assert.equal(uploads[0].buffer[0], 0x89, "the uploaded bytes must be a real PNG");

  assert.equal(sent.length, 1);
  const { attachments } = sent[0];
  assert.equal(attachments.length, 1);
  assert.equal(attachments[0].url, "https://fake-minio.test/cortex-recordings/bot-tables/table.png");
  assert.equal(attachments[0].filetype, "image/png");
});

test("*test svg replies with a friendly error instead of throwing when storage isn't configured", async () => {
  const { StorageNotConfiguredError } = require("../src/mezon/storage");
  const storage = {
    uploadPublicObject: async () => {
      throw new StorageNotConfiguredError("MINIO_PUBLIC_URL chưa cấu hình — xem .env.example.");
    },
  };
  const { router, sent } = makeRouter({ cortex: { resolveChannel: async () => ({ linked: false }) }, storage });

  await assert.doesNotReject(router.handleMessage(baseMessage({ text: "*test svg" })));

  assert.equal(sent.length, 1);
  assert.match(sent[0].content.t, /MINIO_PUBLIC_URL/);
});

test("*test csv sends the sample table as a CSV data: URI attachment", async () => {
  const { router, sent } = makeRouter({ cortex: { resolveChannel: async () => ({ linked: false }) } });

  await router.handleMessage(baseMessage({ text: "*test csv" }));

  assert.equal(sent.length, 1);
  const { attachments } = sent[0];
  assert.equal(attachments.length, 1);
  assert.match(attachments[0].url, /^data:text\/csv;base64,/);
  assert.equal(attachments[0].filetype, "text/csv");
  const decoded = Buffer.from(attachments[0].url.split(",")[1], "base64").toString("utf8");
  assert.match(decoded, /^Tên,Trạng thái,Ghi chú/);
});

test("*test embed sends the sample table as InteractiveBuilder embed fields, not t/mk text", async () => {
  const { router, sent } = makeRouter({ cortex: { resolveChannel: async () => ({ linked: false }) } });

  await router.handleMessage(baseMessage({ text: "*test embed" }));

  assert.equal(sent.length, 1);
  const { content } = sent[0];
  assert.ok(Array.isArray(content.embed), "notice() must produce an embed, not plain t/mk text");
  const fields = content.embed[0].fields;
  // 3 header + 2 sample data rows × 3 columns = 9 cell fields, +2
  // non-inline row-break fields between the 3 rows = 11 (see
  // tableRender.js's tableToEmbedFields on why the row-break exists).
  assert.equal(fields.length, 11);
  assert.equal(fields[0].name, "Tên", "the standalone header row must open with the column labels");
  assert.equal(content.mk, undefined, "embed fields carry the table, not mk ranges");
});

// ── M4: interactive cards ────────────────────────────────────────────────
//
// `plan_proposal` and `ask_choice` reaching Mezon as an embed with
// buttons, and a click on one of those buttons coming back as a real
// action. Same hand-built fakes as above; the cards themselves are
// tested in `planCard.test.js` / `askChoice.test.js`, so these are about
// wiring: which call happens, with what, and what the user is left
// looking at.

const { parseActionId } = require("../src/mezon/actions");

const CHOICE_QUESTIONS = [
  { id: "q1", question: "Deadline khi nào?", options: [{ label: "Thứ 6 này" }, { label: "Tuần sau" }] },
];

/** The `message_button_clicked` shape the SDK delivers. `user_id` is the
 *  human and `sender_id` is the bot — getting those backwards credits the
 *  bot for everything the user does (§VIII bis 8c). */
function buttonEvent(buttonId, { extraData, messageId = "card-msg", channelId = "ch-1" } = {}) {
  return {
    button_id: buttonId,
    message_id: messageId,
    channel_id: channelId,
    user_id: "mezon-u1",
    sender_id: "bot-id",
    extra_data: extraData,
  };
}

function submitIdOf(sentMessage) {
  return sentMessage.content.components[0].components[0].id;
}

test("a plan_proposal event fetches the proposal and sends a preview card after the answer", async () => {
  const calls = [];
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    getPlanProposal: async (id, userId) => {
      calls.push({ id, userId });
      return { status: "pending", items: [{ key: "t1", type: "task", title: "Viết đề cương" }] };
    },
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Mình đề xuất kế hoạch sau." });
      onEvent({ event: "plan_proposal", proposal_id: "p-1", item_count: 1 });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  assert.deepEqual(calls, [{ id: "p-1", userId: "cortex-u1" }], "fetched as the user, not as the service");

  const card = sent[sent.length - 1];
  assert.match(JSON.stringify(card.content), /Viết đề cương/, "the preview must show what would be created");
  assert.deepEqual(parseActionId(submitIdOf(card)), { kind: "plan_approve", targetId: "p-1" });
});

test("a preview that cannot be loaded still tells the user the plan exists, and does not break the answer", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    getPlanProposal: async () => { throw new Error("Cortex timeout sau 30000ms"); },
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Xong rồi nhé." });
      onEvent({ event: "plan_proposal", proposal_id: "p-1", item_count: 3 });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleMessage(baseMessage()));

  assert.match(edits[edits.length - 1].content.t, /Xong rồi nhé\./, "the answer survives a card failing");
  assert.match(sent[sent.length - 1].content.t, /Mở Cortex trên web/);
});

test("an ask_choice event sends a form whose submit button the router can route back", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      onEvent({ event: "token", text: "Cho mình hỏi thêm:" });
      onEvent({ event: "ask_choice", questions: CHOICE_QUESTIONS });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());

  const card = sent[sent.length - 1];
  assert.match(JSON.stringify(card.content), /Deadline khi nào\?/);
  assert.equal(parseActionId(submitIdOf(card)).kind, "ask_submit");
});

test("a button id that is not ours is ignored — a dropdown change fires this same event", async () => {
  // §VIII bis 8b: a SELECT fires `message_button_clicked` on every change,
  // with the select's own id and a bare non-JSON `extra_data`. Treating
  // that as an error would log one every time a user opens a dropdown.
  let identified = false;
  const cortex = {
    resolveChannel: async () => { identified = true; return { linked: true, user_id: "cortex-u1" }; },
  };
  const { router, sent } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleButton(buttonEvent("q0", { extraData: "Tuần sau" })));

  assert.equal(identified, false, "must not even resolve identity for traffic that isn't ours");
  assert.equal(sent.length, 0);
});

test("approving a plan checks it is still pending, then creates it and replaces the card", async () => {
  const calls = [];
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    getPlanProposal: async () => ({ status: "pending", items: [] }),
    approvePlanProposal: async (id, userId) => {
      calls.push({ id, userId });
      return { created_count: 2, failed_count: 0, results: [] };
    },
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleButton(buttonEvent("pa:p-1", { extraData: "" }));

  assert.deepEqual(calls, [{ id: "p-1", userId: "cortex-u1" }]);
  const edit = edits[edits.length - 1];
  assert.equal(edit.messageId, "card-msg", "the card itself is replaced, taking its buttons with it");
  assert.match(edit.content.embed[0].description, /2 mục/);
});

test("a plan that was already approved is not approved a second time — the backend would happily create everything twice", async () => {
  let approved = false;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    getPlanProposal: async () => ({ status: "approved", items: [] }),
    approvePlanProposal: async () => { approved = true; return {}; },
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleButton(buttonEvent("pa:p-1", { extraData: "" }));

  assert.equal(approved, false, "the status check is the only thing standing between a stale button and duplicate tasks");
  assert.match(edits[edits.length - 1].content.embed[0].description, /đã được tạo/);
});

test("rejecting a plan calls reject and creates nothing", async () => {
  let rejected = null;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    getPlanProposal: async () => ({ status: "pending", items: [] }),
    approvePlanProposal: async () => { throw new Error("must not be called"); },
    rejectPlanProposal: async (id) => { rejected = id; return { status: "rejected" }; },
  };
  const { router, edits } = makeRouter({ cortex });

  await router.handleButton(buttonEvent("pr:p-1", { extraData: "" }));

  assert.equal(rejected, "p-1");
  assert.match(edits[edits.length - 1].content.embed[0].title, /bỏ qua/i);
});

test("submitting an answered form sends the picks back as a real chat turn", async () => {
  // The whole point: `ask_user_choice` has no endpoint — the answer's
  // only destination is the conversation, as the user's next message.
  const streamed = [];
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ message, onEvent }) => {
      streamed.push(message);
      // First turn asks; the second is the one carrying the answer back.
      if (streamed.length === 1) onEvent({ event: "ask_choice", questions: CHOICE_QUESTIONS });
      else onEvent({ event: "token", text: "Rõ rồi." });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());
  const formId = parseActionId(submitIdOf(sent[sent.length - 1])).targetId;

  await router.handleButton(
    buttonEvent(`as:${formId}`, { extraData: JSON.stringify({ q0: "Tuần sau" }) })
  );

  assert.deepEqual(streamed.slice(1), ["1. Deadline khi nào? → Tuần sau"], "the same string the web sends");
  assert.ok(
    edits.some((e) => e.messageId === "card-msg" && /Đã trả lời/.test(JSON.stringify(e.content))),
    "the form is locked into its answers"
  );
});

test("submitting a form with a question left blank asks for it instead of answering on the user's behalf", async () => {
  const twoQuestions = [
    ...CHOICE_QUESTIONS,
    { id: "q2", question: "Ưu tiên?", options: [{ label: "Cao" }, { label: "Thường" }] },
  ];
  let turns = 0;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    streamChat: async ({ onEvent }) => {
      turns++;
      onEvent({ event: "ask_choice", questions: twoQuestions });
      onEvent({ event: "done", conversation_id: "conv-1" });
    },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(baseMessage());
  const formId = parseActionId(submitIdOf(sent[sent.length - 1])).targetId;

  await router.handleButton(
    buttonEvent(`as:${formId}`, { extraData: JSON.stringify({ q0: "Tuần sau" }) })
  );

  assert.equal(turns, 1, "an incomplete form must not reach the model at all");
  assert.match(sent[sent.length - 1].content.t, /Còn thiếu câu 2/);
});

test("a form the bot no longer remembers says so, and points at the way that always works", async () => {
  const cortex = { resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }) };
  const { router, sent } = makeRouter({ cortex });

  await router.handleButton(buttonEvent("as:khong-ton-tai", { extraData: "{}" }));

  assert.match(sent[sent.length - 1].content.t, /hết hạn/);
  assert.match(sent[sent.length - 1].content.t, /tin nhắn thường/);
});

test("an unlinked account cannot act on a card, however visible the buttons are", async () => {
  let approved = false;
  const cortex = {
    resolveChannel: async () => ({ linked: false }),
    getPlanProposal: async () => ({ status: "pending", items: [] }),
    approvePlanProposal: async () => { approved = true; return {}; },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleButton(buttonEvent("pa:p-1", { extraData: "" }));

  assert.equal(approved, false);
  assert.match(sent[sent.length - 1].content.t, /chưa liên kết/);
});
