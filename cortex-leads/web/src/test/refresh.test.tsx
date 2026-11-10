import { describe, expect, it } from 'vitest'
import { api, ApiError } from '../api/client'
import { server } from './harness'

const gone = { __status: 401, body: { detail: 'not signed in' } }

describe('the access token runs out', () => {
  it('swaps it through the refresh token once and repeats the call', async () => {
    let n = 0
    const s = server({ 'GET /classes': () => (++n === 1 ? gone : { items: [] }), 'POST /session/refresh': { csrf: 'again' } })
    expect(await api('GET', '/classes')).toEqual({ items: [] })
    expect(s.calls.map((c) => `${c.method} ${c.path}`)).toEqual(['GET /classes', 'POST /session/refresh', 'GET /classes'])
  })

  it('gives up, as before, when there is no refresh token', async () => {
    const s = server({ 'GET /classes': gone })  // refresh is unlisted: the harness answers it 401
    await expect(api('GET', '/classes')).rejects.toBeInstanceOf(ApiError)
    expect(s.calls.map((c) => c.path)).toEqual(['/classes', '/session/refresh'])
  })

  it('asks once for several calls that fail together', async () => {
    const left = { n: 0 }
    const s = server({ 'GET /a': () => (left.n++ < 3 ? gone : { ok: 'a' }), 'GET /b': { ok: 'b' }, 'POST /session/refresh': { csrf: 'c' } })
    const out = await Promise.all([api('GET', '/a'), api('GET', '/a'), api('GET', '/a')])
    expect(out).toHaveLength(3)
    expect(s.calls.filter((c) => c.path === '/session/refresh')).toHaveLength(1)
  })

  it('never retries a sign-in, and never loops on a refresh that fails', async () => {
    const s = server({ 'POST /session/login': gone })
    await expect(api('POST', '/session/login', { email: 'a@b.vn', password: 'x' })).rejects.toBeInstanceOf(ApiError)
    expect(s.calls).toHaveLength(1)
  })
})
