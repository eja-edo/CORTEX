"use strict";

/**
 * Tests for `CortexClient.streamChat` (F2/M3, R2) — the SSE-consuming half
 * of "DM thường → AI". A real `node:http` server is used rather than a
 * mocked `fetch`, same convention as `server.test.js`: what matters here is
 * the wire contract (headers sent, frames parsed as they arrive, non-2xx
 * and timeout handling), not any particular fetch mock's behaviour.
 */

const http = require("node:http");
const test = require("node:test");
const assert = require("node:assert/strict");

process.env.MEZON_BOT_ID = process.env.MEZON_BOT_ID || "test-bot";
process.env.MEZON_BOT_TOKEN = process.env.MEZON_BOT_TOKEN || "test-token";
process.env.CORTEX_INTERNAL_API_KEY = process.env.CORTEX_INTERNAL_API_KEY || "test-key-123";
process.env.LOG_LEVEL = "error";

const { CortexClient, CortexError } = require("../src/cortex");

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

function sseHandler(events, { delayMs = 0 } = {}) {
  return async (req, res) => {
    req.lastHeaders = req.headers;
    let body = "";
    for await (const chunk of req) body += chunk;
    req.lastBody = body;

    res.writeHead(200, { "Content-Type": "text/event-stream" });
    for (const event of events) {
      if (delayMs) await new Promise((r) => setTimeout(r, delayMs));
      res.write(`data: ${JSON.stringify(event)}\n\n`);
    }
    res.end();
  };
}

test("sends X-Internal-API-Key, X-User-ID, surface=mezon, and model=auto", async () => {
  let seenHeaders, seenBody;
  const handler = async (req, res) => {
    seenHeaders = req.headers;
    let body = "";
    for await (const chunk of req) body += chunk;
    seenBody = JSON.parse(body);
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write(`data: ${JSON.stringify({ event: "done", conversation_id: "c1" })}\n\n`);
    res.end();
  };

  await withServer(handler, async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 2000 });
    await client.streamChat({ userId: "u-1", message: "hi", onEvent: () => {} });
  });

  assert.equal(seenHeaders["x-internal-api-key"], "test-key-123");
  assert.equal(seenHeaders["x-user-id"], "u-1");
  assert.deepEqual(seenBody, { message: "hi", surface: "mezon", model: "auto" });
});

test("calls onEvent once per frame, in order", async () => {
  const events = [
    { event: "token", text: "Xin " },
    { event: "token", text: "chào" },
    { event: "done", conversation_id: "c1" },
  ];
  const received = [];

  await withServer(sseHandler(events), async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 2000 });
    await client.streamChat({ userId: "u-1", message: "hi", onEvent: (e) => received.push(e) });
  });

  assert.deepEqual(received, events);
});

test("a frame split across TCP chunks is still parsed whole", async () => {
  const payload = JSON.stringify({ event: "token", text: "chào bạn" });
  const handler = async (req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    // Split mid-frame on purpose — the client must buffer until it sees
    // the blank-line frame terminator, not parse per `write()` call.
    res.write(`data: ${payload.slice(0, 10)}`);
    await new Promise((r) => setTimeout(r, 20));
    res.write(`${payload.slice(10)}\n\n`);
    res.write(`data: ${JSON.stringify({ event: "done", conversation_id: "c1" })}\n\n`);
    res.end();
  };
  const received = [];

  await withServer(handler, async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 2000 });
    await client.streamChat({ userId: "u-1", message: "hi", onEvent: (e) => received.push(e) });
  });

  assert.equal(received.length, 2);
  assert.deepEqual(received[0], { event: "token", text: "chào bạn" });
});

test("a non-2xx response throws CortexError with the response status", async () => {
  const handler = (req, res) => {
    res.writeHead(403, { "Content-Type": "text/plain" });
    res.end("Invalid internal API key");
  };

  await withServer(handler, async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "wrong-key", timeoutMs: 2000 });
    await assert.rejects(
      client.streamChat({ userId: "u-1", message: "hi", onEvent: () => {} }),
      (err) => {
        assert.ok(err instanceof CortexError);
        assert.equal(err.status, 403);
        return true;
      }
    );
  });
});

test("a slow-but-steadily-streaming response does not time out, even past the idle window", async () => {
  // Four chunks, 40ms apart, against a 60ms idle timeout: each chunk
  // arrives well within the idle window of the *previous* one, so the
  // total 160ms run must not trip a timeout that only fires on silence —
  // this is the fixed-deadline bug (a real agent turn with tool calls
  // legitimately runs past 30s while still actively streaming).
  const events = [
    { event: "token", text: "một " },
    { event: "token", text: "hai " },
    { event: "token", text: "ba " },
    { event: "done", conversation_id: "c1" },
  ];
  const received = [];

  await withServer(sseHandler(events, { delayMs: 40 }), async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 60 });
    await client.streamChat({ userId: "u-1", message: "hi", onEvent: (e) => received.push(e) });
  });

  assert.deepEqual(received, events);
});

test("silence between chunks past the idle window still times out", async () => {
  const handler = async (req, res) => {
    res.writeHead(200, { "Content-Type": "text/event-stream" });
    res.write(`data: ${JSON.stringify({ event: "token", text: "một" })}\n\n`);
    // Then goes silent for longer than the idle timeout below.
  };

  await withServer(handler, async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 60 });
    await assert.rejects(
      client.streamChat({ userId: "u-1", message: "hi", onEvent: () => {} }),
      (err) => {
        assert.ok(err instanceof CortexError);
        assert.equal(err.status, 408);
        return true;
      }
    );
  });
});

test("a stream that never responds times out as a CortexError", async () => {
  const handler = () => {
    /* never writes a response — simulates a hung backend */
  };

  await withServer(handler, async (baseUrl) => {
    const client = new CortexClient({ baseUrl, internalApiKey: "test-key-123", timeoutMs: 100 });
    await assert.rejects(
      client.streamChat({ userId: "u-1", message: "hi", onEvent: () => {} }),
      (err) => {
        assert.ok(err instanceof CortexError);
        assert.equal(err.status, 408);
        return true;
      }
    );
  });
});
