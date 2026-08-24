"use strict";

/**
 * Public object hosting for attachments too big for a `data:` URI.
 *
 * `*test csv` proved `data:` URIs work for a genuinely small payload (a
 * few hundred bytes), but `*test svg`'s rasterised PNG (~10KB base64)
 * disconnected the socket every time — not the encoding bug fixed in
 * `attachment.js` (that one threw client-side; this one doesn't: the
 * bytes go out fine and the *server* drops the connection right after,
 * consistent with a message-size limit on the Mezon realtime gateway
 * itself). `ApiMessageAttachment.url` has to be a real fetchable link
 * instead — this bot has no public URL of its own (`server.js` binds
 * `127.0.0.1` on purpose), so it uploads to the MinIO instance this repo
 * already runs (`infrastructure/docker-compose.yml`, bucket
 * `cortex-recordings`, already anonymous-download from the video-upload
 * feature) and returns a link to that.
 *
 * Two different hosts, deliberately: `endpoint` is where *this process*
 * reaches MinIO to `putObject` — same machine, so plain `localhost:9002`
 * is fine. `publicBaseUrl` is what *Mezon's own servers* fetch the
 * uploaded object from to render it — `localhost` from their side would
 * resolve to themselves, not this machine, so that has to be a real
 * public URL (a VS Code Dev Tunnel pointed at the MinIO port, in dev).
 * Signing a presigned GET URL against the internal endpoint would not
 * work here either: SigV4 bakes the `Host` header into the signature, and
 * the tunnel presents a different `Host` than `localhost:9002` on the way
 * back in — so this relies on the bucket being anonymous-download instead
 * of presigning, same as the existing video bucket already is.
 */

const Minio = require("minio");
const { config } = require("../config");

class StorageNotConfiguredError extends Error {}

let _client = null;

function _parseEndpoint(endpoint) {
  const withScheme = /^https?:\/\//.test(endpoint) ? endpoint : `http://${endpoint}`;
  const url = new URL(withScheme);
  return {
    endPoint: url.hostname,
    port: url.port ? Number(url.port) : url.protocol === "https:" ? 443 : 80,
    useSSL: url.protocol === "https:",
  };
}

function _getClient() {
  const { endpoint, accessKey, secretKey } = config.storage;
  if (!endpoint || !accessKey || !secretKey) {
    throw new StorageNotConfiguredError(
      "MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY chưa cấu hình — xem .env.example."
    );
  }
  if (!_client) {
    _client = new Minio.Client({ ...(_parseEndpoint(endpoint)), accessKey, secretKey });
  }
  return _client;
}

/** Uploads `buffer` under `bot-tables/<key>` and returns a URL Mezon's
 *  servers can fetch directly — not a `data:` URI, a real link. Throws
 *  `StorageNotConfiguredError` if the MINIO_* env vars are unset, and
 *  lets any upload/network error propagate — callers decide how to tell
 *  the user, this module only knows how to talk to MinIO. */
async function uploadPublicObject(buffer, { key, contentType }) {
  const { publicBaseUrl, bucket } = config.storage;
  if (!publicBaseUrl) {
    throw new StorageNotConfiguredError("MINIO_PUBLIC_URL chưa cấu hình — xem .env.example.");
  }
  const client = _getClient();
  const objectName = `bot-tables/${key}`;
  await client.putObject(bucket, objectName, buffer, buffer.length, { "Content-Type": contentType });
  return `${publicBaseUrl}/${bucket}/${objectName}`;
}

module.exports = { uploadPublicObject, StorageNotConfiguredError };
