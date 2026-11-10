import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import type { Me } from '../api/types'
import type { Perm } from '../api/enums'

const STAFF_PERMS: Perm[] = ['inbox.use', 'skills.read', 'skills.draft', 'sandboxes.read', 'catalog.read', 'audit.own', 'account.self']  // customer care only
const CLASS_PERMS: Perm[] = ['lessons.read', 'lessons.upload', 'lessons.release', 'grading.use', 'classes.all', 'templates.manage']
const TEACHER_PERMS: Perm[] = ['lessons.read', 'lessons.upload', 'lessons.release', 'grading.use', 'classes.edit', 'audit.own', 'account.self']
const OWNER_PERMS: Perm[] = [...STAFF_PERMS, ...CLASS_PERMS, 'classes.edit', 'ai.pause', 'skills.manage', 'sandboxes.manage', 'tools.manage', 'sources.manage', 'assistant.use', 'audit.all', 'audit.admin', 'team.manage', 'settings.manage', 'catalog.manage']
export const OWNER: Me = { role: 'owner', staff_ref: 'owner', tenant: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', csrf: 'csrf-token-1', ai: 'running', mode: 'manual', needs_person: 3,
  email: 'chu@minhkhai.vn', name: 'Chủ Minh Khai', permissions: OWNER_PERMS }
export const STAFF: Me = { ...OWNER, role: 'staff', staff_ref: 'nv1', email: 'nv1@minhkhai.vn', name: 'Nhân viên Một', permissions: STAFF_PERMS }
/** A session that holds the class permissions without being the owner. The class screens decide by permission, not by role, so their tests use this
 *  where they once used the staff role, which since 2026-11-06 has no class work at all. */
export const CLASS_STAFF: Me = { ...STAFF, permissions: [...STAFF_PERMS, ...CLASS_PERMS] }
export const TEACHER: Me = { ...OWNER, role: 'teacher', staff_ref: 'co-mai', email: 'co.mai@minhkhai.vn', name: 'Cô Mai', needs_person: 0, permissions: TEACHER_PERMS }

type Reply = unknown | ((body: unknown, init: RequestInit) => unknown)
export interface Call { method: string; path: string; body: unknown; csrf: string | null }

/** A fake server: "METHOD /path" -> JSON (or a function of the body, or {status, body}). Unlisted calls fail the test. */
export function server(table: Record<string, Reply>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = String(url).replace('/api/v1', '')
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : undefined  // a file sent as it is has no JSON body
    calls.push({ method, path, body, csrf: new Headers(init.headers).get('X-CSRF-Token') })
    const hit = table[`${method} ${path}`] ?? table[`${method} ${path.split('?')[0]}`]
    if (hit === undefined && method === 'POST' && path === '/session/refresh') {  // nobody listed it: the person has no refresh token
      return new Response(JSON.stringify({ detail: { code: 'REFRESH_INVALID' } }), { status: 401, headers: { 'Content-Type': 'application/json' } })
    }
    if (hit === undefined) throw new Error(`unexpected request: ${method} ${path}`)
    const out = typeof hit === 'function' ? (hit as (b: unknown, i: RequestInit) => unknown)(body, init) : hit
    const res = out as { __status?: number; body?: unknown }
    const status = res && typeof res === 'object' && '__status' in res ? res.__status! : 200
    const payload = res && typeof res === 'object' && '__status' in res ? res.body : out
    return new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
  }))
  return { calls, posted: (path: string) => calls.filter((c) => c.method === 'POST' && c.path === path) }
}
export const fail = (status: number, detail: unknown) => ({ __status: status, body: { detail } })

export function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchInterval: false, staleTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}><App /></MemoryRouter>
    </QueryClientProvider>,
  )
}
