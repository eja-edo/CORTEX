import { describe, it, expect } from 'vitest'
import { uuid7 } from '../uuid'

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

/** Milliseconds since the epoch encoded in the leading 48 bits. */
function timestampOf(id: string): number {
  return parseInt(id.slice(0, 8) + id.slice(9, 13), 16)
}

describe('uuid7', () => {
  it('emits canonical UUID text', () => {
    expect(uuid7()).toMatch(UUID_RE)
  })

  it('sets the version and variant bits required by RFC 9562', () => {
    for (let i = 0; i < 50; i++) {
      const id = uuid7()
      expect(id[14]).toBe('7')
      expect('89ab').toContain(id[19])
    }
  })

  it('encodes the current time in the leading 48 bits', () => {
    const before = Date.now()
    const id = uuid7()
    const after = Date.now()
    expect(timestampOf(id)).toBeGreaterThanOrEqual(before)
    expect(timestampOf(id)).toBeLessThanOrEqual(after)
  })

  it('carries non-decreasing timestamps across a burst', () => {
    // The point of v7 over v4: the sortable prefix advances with wall time, so
    // Postgres keeps appending to the right edge of the index. Ids minted
    // inside the same millisecond share a prefix and have a random tail, so
    // their relative order is not defined — only the prefix is checked here.
    const ids: string[] = []
    for (let i = 0; i < 200; i++) ids.push(uuid7())
    const byTimestamp = [...ids].sort((a, b) => timestampOf(a) - timestampOf(b))
    expect(byTimestamp).toEqual(ids)
  })

  it('does not collide within a single millisecond', () => {
    const ids = new Set<string>()
    for (let i = 0; i < 10000; i++) ids.add(uuid7())
    expect(ids.size).toBe(10000)
  })
})
