"use strict";

/**
 * Bot entry point (M1).
 *
 * Wiring only — every decision lives in the module it belongs to. What is
 * here that is not obvious:
 *
 * - Config is validated before the socket opens, so a missing setting is a
 *   refusal to start rather than a bot that looks healthy and fails one
 *   user at a time.
 * - Shutdown closes the socket. Leaving it open across a restart leaves
 *   two connections on one bot token, and the gateway then has a choice
 *   about which one gets the messages.
 */

const { config } = require("./config");
const { logger } = require("./logger");
const { MezonGateway } = require("./mezon/client");
const { CortexClient } = require("./cortex");
const storage = require("./mezon/storage");
const { CommandRegistry } = require("./commands/registry");
const { MessageRouter } = require("./router");
const { startServer } = require("./server");
const { linkCommand } = require("./commands/link");
const { pingCommand, helpCommand } = require("./commands/basic");
const { testCommand } = require("./commands/test");
const { modelCommand } = require("./commands/model");
const { todayCommand, nextCommand } = require("./commands/agenda");
const { tasksCommand } = require("./commands/tasks");
const { newTaskCommand } = require("./commands/newTask");
const { muteCommand } = require("./commands/mute");
const { inboxCommand } = require("./commands/inbox");

async function main() {
  logger.info("Cortex Mezon bot starting", {
    cortexUrl: config.cortex.baseUrl,
    prefix: config.bot.commandPrefix,
    keepThinking: config.bot.keepThinking,
  });

  const cortex = new CortexClient();

  // Reported, not fatal: the backend may simply be starting alongside us,
  // and refusing to boot would turn a slow dependency into an outage.
  const backendUp = await cortex.health();
  logger.info(backendUp ? "Cortex reachable" : "Cortex NOT reachable — bot will still start");

  const registry = new CommandRegistry({ prefix: config.bot.commandPrefix })
    .register(helpCommand)
    .register(pingCommand)
    .register(linkCommand)
    .register(todayCommand)
    .register(nextCommand)
    .register(tasksCommand)
    .register(newTaskCommand)
    .register(muteCommand)
    .register(inboxCommand)
    .register(modelCommand)
    .register(testCommand);

  const gateway = await new MezonGateway().connect();

  const router = new MessageRouter({
    gateway,
    registry,
    cortex,
    storage,
    prefix: config.bot.commandPrefix,
    keepThinking: config.bot.keepThinking,
  });

  gateway
    .onUserMessage((message) => router.handleMessage(message))
    .onButtonClicked((event) => router.handleButton(event));

  // Started after the gateway, so the backend never gets a 2xx for a
  // delivery the bot could not actually have sent.
  const server = await startServer({ gateway });

  logger.info("Bot ready", { commands: registry.list().map((c) => c.name) });

  const shutdown = async (signal) => {
    logger.info(`${signal} — shutting down`);
    server.close();
    await gateway.close();
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

if (require.main === module) {
  main().catch((err) => {
    logger.error("fatal", { error: err?.message, stack: err?.stack });
    process.exit(1);
  });
}

module.exports = { main };
