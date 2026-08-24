"use strict";

/**
 * Tests for `mezon/storage.js`'s config-guard behaviour — not a real
 * upload round-trip against MinIO, since that would make this suite
 * depend on a live service being up. The real upload path was verified
 * against the actual dev MinIO instance while diagnosing why `*test svg`
 * disconnected the socket (see that module's docstring); what's worth
 * pinning here is that missing configuration fails with a clear,
 * recognisable error instead of a confusing one from deep inside the
 * `minio` client library.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { config } = require("../src/config");
const { uploadPublicObject, StorageNotConfiguredError } = require("../src/mezon/storage");

function withStorageConfig(overrides, fn) {
  const original = { ...config.storage };
  Object.assign(config.storage, overrides);
  return fn().finally(() => Object.assign(config.storage, original));
}

test("uploadPublicObject rejects with StorageNotConfiguredError when MINIO_ENDPOINT is unset", async () => {
  await withStorageConfig({ endpoint: null }, async () => {
    await assert.rejects(
      uploadPublicObject(Buffer.from("x"), { key: "a.png", contentType: "image/png" }),
      StorageNotConfiguredError
    );
  });
});

test("uploadPublicObject rejects with StorageNotConfiguredError when MINIO_PUBLIC_URL is unset", async () => {
  await withStorageConfig(
    { endpoint: "localhost:9002", accessKey: "x", secretKey: "y", publicBaseUrl: null },
    async () => {
      await assert.rejects(
        uploadPublicObject(Buffer.from("x"), { key: "a.png", contentType: "image/png" }),
        StorageNotConfiguredError
      );
    }
  );
});
