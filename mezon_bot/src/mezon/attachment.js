"use strict";

/**
 * Builds a complete `ApiMessageAttachment` — every field the SDK's
 * protobuf encoder touches, not just the ones this bot happens to set.
 *
 * `mezon-sdk`'s `MessageAttachment.encode` guards each field with
 * `!== ""` / `!== 0` before writing it (the protobuf3 "only send
 * non-default values" convention) — but that compares against the
 * field's zero value, not against `undefined`. An attachment built as
 * `{url, filetype, filename}` leaves `thumbnail`/`size`/`width`/
 * `height`/`duration` as `undefined`, which is `!== ""`/`!== 0`, so the
 * encoder tries to write them anyway — and `.string(undefined)` throws
 * inside `Buffer.byteLength` (confirmed by calling `MessageAttachment.
 * encode` directly on an attachment shaped like ours). That throw fires
 * mid-write on the live socket, which is what was taking the connection
 * down (`[mezon-sdk] Disconnected!`, then `message handler threw {}` —
 * empty because the SDK's own catch discards whatever `err` actually
 * was) every time this bot sent an image or `data:` URI attachment.
 * Filling in every field with its real zero value keeps every guard
 * clause `false`, so the encoder never touches them.
 */
function normalizeAttachment({
  url = "",
  filetype = "",
  filename = "",
  size = 0,
  width = 0,
  height = 0,
  thumbnail = "",
  duration = 0,
} = {}) {
  return { url, filetype, filename, size, width, height, thumbnail, duration };
}

module.exports = { normalizeAttachment };
