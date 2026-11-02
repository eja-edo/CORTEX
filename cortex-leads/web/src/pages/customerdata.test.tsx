import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Conversation } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const CONV: Conversation = { id: 'c1', name: 'Nguyễn Văn An', channel: 'messenger', state: 'open', intent: null, owner: null, decision_maker: null, promised_date: null,
  window: { open: true, basis: 'free', expires_at: null }, messages: [], drafts: [], facts: [], bookings: [], open_slots: [], log: [] }
const LIST = { items: [{ id: 'c1', name: 'Nguyễn Văn An', snippet: 'Chào', at: '2026-10-20T01:00:00Z', badges: ['need_human'], state: 'open', channel: 'messenger' }], counts: { need_human: 1, waiting: 0, silent: 0, all: 1 } }
const BASE = { 'GET /conversations?filter=need_human': LIST, 'GET /conversations/c1': CONV }

describe('Dữ liệu của khách', () => {
  it('is not offered to staff', async () => {
    server({ 'GET /session': STAFF, ...BASE })
    renderApp('/inbox/c1')
    await screen.findByLabelText('Hồ sơ khách')
    expect(screen.queryByText('Dữ liệu của khách')).toBeNull()
  })

  it('asks first, says what will go, and reports what could not be reached afterwards', async () => {
    const s = server({ 'GET /session': OWNER, ...BASE, 'POST /customers/c1/erase': { erased: { messages: 3 }, not_reached: ['Nhật ký hoạt động (bất biến).'] } })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Xoá dữ liệu khách/ }))
    expect(s.calls.some((c) => c.method === 'POST')).toBe(false)  // a question first
    expect(screen.getByText(/Không hoàn tác được/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Xoá vĩnh viễn' }))
    expect(await screen.findByText(/Đã xoá dữ liệu cá nhân/)).toBeInTheDocument()
    expect(screen.getByText(/bất biến/)).toBeInTheDocument()
    expect(s.posted('/customers/c1/erase')[0].body).toEqual({ confirm: true })
  })

  it('can back out', async () => {
    const s = server({ 'GET /session': OWNER, ...BASE })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Xoá dữ liệu khách/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Không' }))
    expect(screen.getByRole('button', { name: /Xoá dữ liệu khách/ })).toBeInTheDocument()
    expect(s.calls.some((c) => c.method === 'POST')).toBe(false)
  })

  it('says why when a message is being sent', async () => {
    server({ 'GET /session': OWNER, ...BASE, 'POST /customers/c1/erase': fail(409, { code: 'PENDING_WORK', message: 'x' }) })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Xoá dữ liệu khách/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Xoá vĩnh viễn' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('đang được gửi đi'))
  })

  it('downloads a copy through the export endpoint', async () => {
    URL.createObjectURL = () => 'blob:x'
    URL.revokeObjectURL = () => undefined
    const s = server({ 'GET /session': OWNER, ...BASE, 'GET /customers/c1/export': { contact: { name: 'An' }, messages: [] } })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Tải bản sao/ }))
    await waitFor(() => expect(s.calls.some((c) => c.path === '/customers/c1/export')).toBe(true))
  })
})
