"use strict";

/**
 * Tests for `OrchestratorClient` — login, the 401-retries-once rule, the
 * two REST reads, and basic SSE frame dispatch off `streamMetadata`. A real
 * `node:http` server is used throughout, same convention as `cortex.test.js`:
 * what matters is the wire contract, not any particular fetch mock.
 */

const http = require("node:http");
const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const { OrchestratorClient, OrchestratorError } = require("../src/orchestrator");

async function withServer(handler, fn) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  try {
    return await fn(`http://127.0.0.1:${port}`);
  } finally {
    server.close();
  }
}

function readBody(req) {
  return new Promise((resolve) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => resolve(body));
  });
}

function jsonResponse(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

test("logs in with the configured Mezon bot credentials and caches the token", async () => {
  let loginCalls = 0;
  const handler = async (req, res) => {
    if (req.method === "POST" && req.url === "/auth/mezon/bot/login") {
      loginCalls++;
      const body = JSON.parse(await readBody(req));
      assert.deepEqual(body, { account: { appid: "bot-1", token: "secret-1" } });
      return jsonResponse(res, 200, { access_token: "tok-1" });
    }
    if (req.url === "/rooms/id/r1") {
      assert.equal(req.headers.authorization, "Bearer tok-1");
      return jsonResponse(res, 200, { status: "ok", room: { id: "r1", participants: [] } });
    }
    return jsonResponse(res, 404, { detail: "not found" });
  };

  await withServer(handler, async (baseUrl) => {
    const client = new OrchestratorClient({ baseUrl, botId: "bot-1", botToken: "secret-1", timeoutMs: 2000 });
    await client.getRoomById("r1");
    await client.getRoomById("r1");
  });

  assert.equal(loginCalls, 1);
});

test("getRoomById and getSummaryByRoomId unwrap .room / .data", async () => {
  const handler = async (req, res) => {
    if (req.url === "/auth/mezon/bot/login") return jsonResponse(res, 200, { access_token: "tok-1" });
    if (req.url === "/rooms/id/r1") return jsonResponse(res, 200, { status: "ok", room: { id: "r1" } });
    if (req.url === "/summary/room/id/r1") {
      return jsonResponse(res, 200, { status: "ok", data: { room_id: "r1", summary_data: {} } });
    }
    return jsonResponse(res, 404, { detail: "not found" });
  };

  await withServer(handler, async (baseUrl) => {
    const client = new OrchestratorClient({ baseUrl, botId: "b", botToken: "t", timeoutMs: 2000 });
    assert.deepEqual(await client.getRoomById("r1"), { id: "r1" });
    assert.deepEqual(await client.getSummaryByRoomId("r1"), { room_id: "r1", summary_data: {} });
  });
});

test("a 401 triggers exactly one fresh login and retry, then succeeds", async () => {
  let loginCalls = 0;
  const handler = async (req, res) => {
    if (req.url === "/auth/mezon/bot/login") {
      loginCalls++;
      return jsonResponse(res, 200, { access_token: `tok-${loginCalls}` });
    }
    if (req.url === "/rooms/id/r1") {
      // The stale token this client started with — set below without ever
      // logging in for it — is what should draw the 401 that triggers the
      // one real login this test expects.
      if (req.headers.authorization === "Bearer stale-token") {
        return jsonResponse(res, 401, { detail: "expired" });
      }
      assert.equal(req.headers.authorization, "Bearer tok-1");
      return jsonResponse(res, 200, { status: "ok", room: { id: "r1" } });
    }
    return jsonResponse(res, 404, {});
  };

  await withServer(handler, async (baseUrl) => {
    const client = new OrchestratorClient({ baseUrl, botId: "b", botToken: "t", timeoutMs: 2000 });
    client._accessToken = "stale-token"; // pretend a stale token was already cached
    const room = await client.getRoomById("r1");
    assert.deepEqual(room, { id: "r1" });
  });

  assert.equal(loginCalls, 1);
});

test("a non-2xx, non-401 response throws OrchestratorError with the response status", async () => {
  const handler = async (req, res) => {
    if (req.url === "/auth/mezon/bot/login") return jsonResponse(res, 200, { access_token: "tok-1" });
    return jsonResponse(res, 403, { detail: "missing rooms:view_all" });
  };

  await withServer(handler, async (baseUrl) => {
    const client = new OrchestratorClient({ baseUrl, botId: "b", botToken: "t", timeoutMs: 2000 });
    await assert.rejects(client.getRoomById("r1"), (err) => {
      assert.ok(err instanceof OrchestratorError);
      assert.equal(err.status, 403);
      return true;
    });
  });
});

test("streamMetadata parses each SSE frame and calls onEvent in order", async () => {
  const events = [
    { event_type: "room_ended", room_id: "r1", room_name: "Room 1" },
    { event_type: "room_summary_done", room_id: "r1", room_name: "Room 1" },
  ];
  const handler = async (req, res) => {
    if (req.url === "/auth/mezon/bot/login") return jsonResponse(res, 200, { access_token: "tok-1" });
    if (req.url === "/sse/metadata") {
      assert.equal(req.headers.authorization, "Bearer tok-1");
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      for (const event of events) res.write(`data: ${JSON.stringify(event)}\n\n`);
      // Deliberately never `res.end()` — the client should still have
      // dispatched both frames already; the connection is torn down by
      // `stop()` closing the server below.
      return;
    }
    return jsonResponse(res, 404, {});
  };

  const received = [];
  await withServer(handler, async (baseUrl) => {
    const client = new OrchestratorClient({ baseUrl, botId: "b", botToken: "t", timeoutMs: 2000 });
    client.streamMetadata({ onEvent: (e) => received.push(e) });
    // Give the async connect+read loop a tick to consume both frames.
    await new Promise((resolve) => setTimeout(resolve, 50));
    client.stop();
  });

  assert.deepEqual(received, events);
});
