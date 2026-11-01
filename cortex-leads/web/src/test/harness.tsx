import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import App from '../App'
import type { Me } from '../api/types'

const STAFF_PERMS = ['inbox.use', 'skills.read', 'skills.draft', 'sandboxes.read', 'lessons.read', 'lessons.upload', 'lessons.release', 'grading.use', 'audit.own', 'account.self']
const OWNER_PERMS = [...STAFF_PERMS, 'ai.pause', 'skills.manage', 'sandboxes.manage', 'tools.manage', 'sources.manage', 'assistant.use', 'audit.all', 'audit.admin', 'team.manage']
export const OWNER: Me = { role: 'owner', staff_ref: 'owner', tenant: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', csrf: 'csrf-token-1', ai: 'running', mode: 'manual', needs_person: 3,
  email: 'chu@minhkhai.vn', name: 'Chủ Minh Khai', must_change_password: false, permissions: OWNER_PERMS }
export const STAFF: Me = { ...OWNER, role: 'staff', staff_ref: 'nv1', email: 'nv1@minhkhai.vn', name: 'Nhân viên Một', permissions: STAFF_PERMS }

type Reply = unknown | ((body: unknown, init: RequestInit) => unknown)
export interface Call { method: string; path: string; body: unknown; csrf: string | null }

/** A fake server: "METHOD /path" -> JSON (or a function of the body, or {status, body}). Unlisted calls fail the test. */
export function server(table: Record<string, Reply>) {
  const calls: Call[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    const path = String(url).replace('/api/v1', '')
    const body = init.body ? JSON.parse(String(init.body)) : undefined
    calls.push({ method, path, body, csrf: new Headers(init.headers).get('X-CSRF-Token') })
    const hit = table[`${method} ${path}`] ?? table[`${method} ${path.split('?')[0]}`]
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
