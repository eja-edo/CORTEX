"use strict";

/**
 * Tests for `*model` — the picker, its submission, and the two things
 * that must not drift: the catalogue comes from the backend, and the
 * choice is stored there too.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { MessageRouter } = require("../src/router");
const { CommandRegistry } = require("../src/commands/registry");
const { modelCommand } = require("../src/commands/model");
const { parseActionId } = require("../src/mezon/actions");
const { renderModelPicker } = require("../src/mezon/modelCard");

const MODELS = [
  { id: "free_auto", label: "Auto (default)" },
  { id: "gemini/gemma-4-31b-it", label: "Gemma 4 31B" },
];

function makeRouter({ cortex } = {}) {
  const sent = [];
  const edits = [];
  let nextId = 1;
  const gateway = {
    sendToChannel: async (channelId, content) => {
      const id = `msg-${nextId++}`;
      sent.push({ channelId, content, id });
      return { id };
    },
    editMessage: async (channelId, messageId, content) => {
      edits.push({ channelId, messageId, content });
      return { id: messageId };
    },
  };
  const registry = new CommandRegistry({ prefix: "*" }).register(modelCommand);
  const router = new MessageRouter({ gateway, registry, cortex, prefix: "*" });
  return { router, sent, edits };
}

const message = (text) => ({ text, senderId: "mezon-u1", channelId: "ch-1", scope: "dm", mode: 4 });

function buttonEvent(buttonId, values) {
  return {
    button_id: buttonId,
    message_id: "card-msg",
    channel_id: "ch-1",
    user_id: "mezon-u1",
    sender_id: "bot-id",
    extra_data: JSON.stringify(values),
  };
}

const submitIdOf = (m) => m.content.components[0].components[0].id;

test("the picker is built from the backend's catalogue, never a list baked into the bot", async () => {
  let listedAs = null;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    listModels: async (userId) => { listedAs = userId; return MODELS; },
    getPreferences: async () => ({ chat_model: null }),
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(message("*model"));

  assert.equal(listedAs, "cortex-u1", "listed as the user, not as the service");
  const options = sent[0].content.embed[0].fields[0].inputs.component;
  assert.deepEqual(options.map((o) => o.value), MODELS.map((m) => m.id));
  assert.equal(parseActionId(submitIdOf(sent[0])).kind, "model_submit");
});

test("the model in use is named, since a Mezon radio cannot show a selected option", () => {
  const content = renderModelPicker(MODELS, "gemini/gemma-4-31b-it", "f1");

  assert.match(content.embed[0].description, /Gemma 4 31B/);
  const options = content.embed[0].fields[0].inputs.component;
  assert.match(options[1].label, /đang dùng/);
  assert.ok(!options[0].label.includes("đang dùng"));
});

test("a picker still renders when the current choice cannot be read — picking must work regardless", async () => {
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    listModels: async () => MODELS,
    getPreferences: async () => { throw new Error("Cortex timeout sau 30000ms"); },
  };
  const { router, sent } = makeRouter({ cortex });

  await assert.doesNotReject(router.handleMessage(message("*model")));
  assert.match(JSON.stringify(sent[0].content), /Gemma 4 31B/);
});

test("submitting stores the choice on the backend, not in this process", async () => {
  // A setting that resets on restart is worse than no setting, and bot
  // restarts are routine.
  const saved = [];
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    listModels: async () => MODELS,
    getPreferences: async () => ({ chat_model: null }),
    setChatModel: async (modelId, userId) => { saved.push({ modelId, userId }); return {}; },
  };
  const { router, sent, edits } = makeRouter({ cortex });

  await router.handleMessage(message("*model"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`ms:${formId}`, { model: "gemini/gemma-4-31b-it" }));

  assert.deepEqual(saved, [{ modelId: "gemini/gemma-4-31b-it", userId: "cortex-u1" }]);
  const edit = edits[edits.length - 1];
  assert.equal(edit.messageId, "card-msg", "the picker is replaced, taking its button with it");
  assert.match(edit.content.embed[0].description, /Gemma 4 31B/);
  assert.match(edit.content.embed[0].description, /Mezon/, "and says the change is scoped to this surface");
});

test("submitting with nothing picked asks again instead of saving something", async () => {
  let saved = false;
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    listModels: async () => MODELS,
    getPreferences: async () => ({ chat_model: null }),
    setChatModel: async () => { saved = true; return {}; },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(message("*model"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await router.handleButton(buttonEvent(`ms:${formId}`, {}));

  assert.equal(saved, false);
  assert.match(sent[sent.length - 1].content.t, /Chưa chọn model/);
});

test("a backend rejection reaches the user instead of looking like it worked", async () => {
  // The backend is what validates the id against the catalogue; a stale
  // picker must not end with a cheerful confirmation.
  const cortex = {
    resolveChannel: async () => ({ linked: true, user_id: "cortex-u1" }),
    listModels: async () => MODELS,
    getPreferences: async () => ({ chat_model: null }),
    setChatModel: async () => { throw new Error("Unknown model: gemini/gemma-4-31b-it"); },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(message("*model"));
  const formId = parseActionId(submitIdOf(sent[0])).targetId;

  await assert.doesNotReject(router.handleButton(buttonEvent(`ms:${formId}`, { model: "gemini/gemma-4-31b-it" })));
  assert.match(sent[sent.length - 1].content.t, /Unknown model/);
});

test("*model needs a linked account — it writes to a Cortex user's preferences", async () => {
  let listed = false;
  const cortex = {
    resolveChannel: async () => ({ linked: false }),
    listModels: async () => { listed = true; return MODELS; },
  };
  const { router, sent } = makeRouter({ cortex });

  await router.handleMessage(message("*model"));

  assert.equal(listed, false);
  assert.match(sent[0].content.t, /chưa liên kết/i);
});
