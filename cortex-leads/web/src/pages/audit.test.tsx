import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { AuditList } from '../api/types'
import { OWNER, STAFF, renderApp, server } from '../test/harness'
import { businessDay } from '../components/format'
import { presetRange } from '../components/DateRange'
import { pageList } from './Audit'

const item = (n: number, over: Record<string, unknown> = {}) => ({
  id: `e${n}`, seq: n, at: '2026-10-21T02:30:00Z', actor: 'staff:owner', role: 'owner', category: 'config', action: 'skill.live',
  result: 'success' as const, summary: `Việc số ${n}`, object: null, ip: '203.0.113.7', has_metadata: false, ...over,
})
const list = (over: Partial<AuditList> = {}): AuditList => ({
  items: [item(3, { has_metadata: true }), item(2, { result: 'failed', actor: 'unknown', summary: 'Đăng nhập thất bại: khoá không tồn tại' }), item(1)],
  total: 53, page: 1, page_size: 20, pages: 3, page_sizes: [10, 20, 50, 100], actors: ['staff:nv1', 'staff:owner'],
  categories: { auth: 'Đăng nhập', config: 'Cấu hình' }, ...over,
})

describe('pageList', () => {
  it('always keeps the first and last page and closes the gaps with an ellipsis', () => {
    expect(pageList(1, 3)).toEqual([1, 2, 3])
    expect(pageList(5, 20)).toEqual([1, '…', 4, 5, 6, '…', 20])
    expect(pageList(2, 20)).toEqual([1, 2, 3, '…', 20])
    expect(pageList(1, 1)).toEqual([1])
  })
})

describe('Audit', () => {
  it('lists events with their result and times in the business timezone, and shows the totals', async () => {
    server({ 'GET /session': OWNER, 'GET /audit': list() })
    renderApp('/audit')
    expect(await screen.findByText('Việc số 3')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getByText('Thất bại')).toBeInTheDocument()
    expect(within(screen.getByRole('table')).getAllByText('09:30 21/10').length).toBe(3) // 02:30Z is 09:30 in Ho Chi Minh
    expect(screen.getByText('Hiển thị 1–20 / 53 dòng')).toBeInTheDocument()
  })

  it('goes to another page and changes the page size, going back to page 1', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /audit': list() })
    renderApp('/audit')
    await screen.findByText('Việc số 3')
    await userEvent.click(screen.getByRole('button', { name: 'Trang 3' }))
    await waitFor(() => expect(s.calls.some((c) => c.path === '/audit?page=3&page_size=20')).toBe(true))
    await userEvent.selectOptions(screen.getByLabelText('Số dòng mỗi trang'), '50')
    await waitFor(() => expect(s.calls.some((c) => c.path === '/audit?page=1&page_size=50')).toBe(true))
  })

  it('filters by actor, group, result and text', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /audit': list() })
    renderApp('/audit')
    await screen.findByText('Việc số 3')
    await userEvent.selectOptions(screen.getByLabelText('Người thực hiện'), 'staff:nv1')
    await userEvent.selectOptions(screen.getByLabelText('Kết quả'), 'failed')
    await userEvent.type(screen.getByPlaceholderText(/Tóm tắt, IP/), '203.0.113.7{enter}')
    await waitFor(() => expect(s.calls.at(-1)?.path).toBe('/audit?page=1&page_size=20&actor=staff%3Anv1&result=failed&q=203.0.113.7'))
  })

  it('sends the chosen days to the server and starts again from page 1', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /audit': list() })
    renderApp('/audit')
    await screen.findByText('Việc số 3')
    await userEvent.click(screen.getByRole('button', { name: 'Trang 2' }))
    await userEvent.click(screen.getByRole('button', { name: /Thời gian/ }))
    await userEvent.click(screen.getByRole('button', { name: '30 ngày qua' }))
    await userEvent.click(screen.getByRole('button', { name: 'Áp dụng' }))
    const r = presetRange('30d', businessDay())
    await waitFor(() => expect(s.calls.at(-1)?.path).toBe(`/audit?page=1&page_size=20&date_from=${r.from}&date_to=${r.to}`))
  })

  it('opens a line to show the metadata, request id and address', async () => {
    server({ 'GET /session': OWNER, 'GET /audit': list(), 'GET /audit/e3': { ...item(3), user_agent: 'Firefox/130', request_id: 'req_abc', session_id: 'fp:12', hash: 'ff00',
      metadata: { attempted: 'fp:eafe146edd', reason: 'unknown_key' } } })
    renderApp('/audit')
    await userEvent.click(await screen.findByText('Việc số 3'))
    const panel = await screen.findByRole('complementary', { name: 'Chi tiết sự kiện' })
    expect(await within(panel).findByText('req_abc')).toBeInTheDocument()
    expect(within(panel).getByText('203.0.113.7')).toBeInTheDocument()
    expect(panel.querySelector('pre')?.textContent).toContain('"reason": "unknown_key"')
  })

  it('lets the owner check the chain and says plainly when a line was altered', async () => {
    server({ 'GET /session': OWNER, 'GET /audit': list(), 'GET /audit/verify': { ok: false, checked: 7, first_bad: '2026-10-21T02:30:00Z' } })
    renderApp('/audit')
    await userEvent.click(await screen.findByRole('button', { name: /Kiểm tra toàn vẹn/ }))
    expect(await screen.findByText(/Phát hiện dòng bị sửa hoặc mất/)).toBeInTheDocument()
  })

  it('shows staff only their own trail: no actor filter, no export, no integrity check', async () => {
    server({ 'GET /session': STAFF, 'GET /audit': list({ actors: ['staff:nv1'] }) })
    renderApp('/audit')
    await screen.findByText('Việc số 3')
    expect(screen.queryByLabelText('Người thực hiện')).toBeNull()
    expect(screen.queryByRole('button', { name: /Kiểm tra toàn vẹn/ })).toBeNull()
    expect(screen.queryByRole('link', { name: /Xuất CSV/ })).toBeNull()
  })
})
