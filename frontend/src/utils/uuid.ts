/**
 * UUIDv7 (RFC 9562) generation.
 *
 * Mirrors `backend/app/ids.py` and `workflow_service/app/core/ids.py`: every id
 * Cortex persists is time-ordered, including the ones minted client-side that
 * end up inside note content and workflow definitions.
 *
 * Layout: 48-bit big-endian millisecond timestamp, 4-bit version (0111),
 * 12 random bits, 2-bit variant (10), 62 random bits.
 *
 * Prefer this over `crypto.randomUUID()` — beyond the ordering, `randomUUID`
 * is only exposed in secure contexts, so it is `undefined` when the dev server
 * is reached over plain HTTP from another device on the LAN.
 * `crypto.getRandomValues` carries no such restriction.
 */
export function uuid7(): string {
  const ts = Date.now()
  const bytes = new Uint8Array(16)

  if (typeof crypto !== 'undefined' && typeof crypto.getRandomValues === 'function') {
    crypto.getRandomValues(bytes)
  } else {
    for (let i = 0; i < 16; i++) bytes[i] = Math.floor(Math.random() * 256)
  }

  // Timestamp occupies bytes 0-5, most significant byte first. Each shift keeps
  // the intermediate below 2^31, so the `& 0xff` coercion to int32 is safe.
  bytes[0] = (ts / 2 ** 40) & 0xff
  bytes[1] = (ts / 2 ** 32) & 0xff
  bytes[2] = (ts / 2 ** 24) & 0xff
  bytes[3] = (ts / 2 ** 16) & 0xff
  bytes[4] = (ts / 2 ** 8) & 0xff
  bytes[5] = ts & 0xff

  bytes[6] = (bytes[6] & 0x0f) | 0x70 // version 7
  bytes[8] = (bytes[8] & 0x3f) | 0x80 // variant 10

  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
