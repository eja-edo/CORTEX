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
const { OrchestratorClient } = require("./orchestrator");
const { RoomWatchService } = require("./roomWatch");
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
const { PendingForms } = require("./mezon/pendingForms");

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

  // Shared with `MessageRouter` below: a project-picker card written here
  // has to be readable back by `_handleProjectPick` when the user answers
  // it, so both need the same store rather than one each.
  const pendingForms = new PendingForms();

  // Optional: orchestrator_service (meeting rooms/summaries) is a separate
  // service this bot may or may not be deployed alongside. Left unwired —
  // not a startup failure — when `ORCHESTRATOR_API_URL` isn't set.
  let roomWatch;
  if (config.orchestrator.baseUrl) {
    const orchestrator = new OrchestratorClient();
    roomWatch = new RoomWatchService({
      gateway,
      cortex,
      orchestrator,
      pendingForms,
      timezone: config.bot.displayTimezone,
    });
  } else {
    logger.info("ORCHESTRATOR_API_URL not set — room-summary feature disabled");
  }

  const router = new MessageRouter({
    gateway,
    registry,
    cortex,
    storage,
    prefix: config.bot.commandPrefix,
    keepThinking: config.bot.keepThinking,
    timezone: config.bot.displayTimezone,
    roomWatch,
    pendingForms,
  });

  gateway
    .onUserMessage((message) => router.handleMessage(message))
    .onButtonClicked((event) => router.handleButton(event));

  // Started after the gateway, so the backend never gets a 2xx for a
  // delivery the bot could not actually have sent.
  const server = await startServer({ gateway });

  // Fire-and-forget: `streamMetadata` reconnects on its own for as long as
  // the process runs, so a failure here must not fail bot startup — it's
  // the same "reported, not fatal" treatment as the Cortex health check
  // above.
  roomWatch?.start();

  logger.info("Bot ready", { commands: registry.list().map((c) => c.name) });

  const shutdown = async (signal) => {
    logger.info(`${signal} — shutting down`);
    roomWatch?.stop();
    server.close();
    await gateway.close();
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));

  // Last-resort net, not a substitute for catching errors at their source.
  // Node 22 kills the process on an unhandled rejection by default — one
  // promise anywhere in the codebase that nobody awaited or `.catch()`ed
  // (a live incident: `mezon-sdk` rejecting a `message.update()` inside a
  // `setTimeout` callback, with the reason a bare, unloggable object) took
  // down every user's conversation, not just the one that triggered it.
  // Logging and continuing turns "the whole bot is down" into "one turn
  // for one user misbehaved", which is the failure this process should
  // actually have.
  process.on("unhandledRejection", (reason) => {
    logger.error("unhandled rejection", {
      error: reason?.message ?? String(reason),
      stack: reason?.stack,
    });
  });
}

if (require.main === module) {
  main().catch((err) => {
    logger.error("fatal", { error: err?.message, stack: err?.stack });
    process.exit(1);
  });
}

module.exports = { main };
