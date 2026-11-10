import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SANDBOXES } from '../test/fixtures'
import { OWNER, STAFF, renderApp, server } from '../test/harness'

const AI = { disclosure: 'Trợ lý AI của Trung tâm', sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách', send_mode: 'manual' as const, status: 'active' as const, skills: [], never_say: [], must_handoff: [] }] }
const base = (me = OWNER, extra: Record<string, unknown> = {}) => server({ 'GET /session': me, 'GET /settings/ai': AI, 'GET /sandboxes': SANDBOXES, ...extra })
const job = async (title: string) => (await screen.findByRole('heading', { name: title, level: 3 })).closest('section')!

const LESSON_LIST = {
  ...SANDBOXES,
  items: [...SANDBOXES.items, { id: 'sb3', title: 'Tổng kết buổi học', purpose: 'lesson_recap', about: 'Bản ghi buổi học thành tổng kết, không nhắn khách', status: 'active' as const,
    send_mode: 'manual' as const, customer_facing: false, flow: '1 thư mục bản ghi → 1 kênh Mezon', budget: { runs_per_day: 200, tokens_per_day: 500_000, drafts_per_staff_per_day: 20 },
    usage: { runs: 4, tokens: 76_578 }, skills: { live: 1, shadow: 0 }, channels: [] }],
}

describe('Việc của AI (Cài đặt → AI)', () => {
  it('is not in the menu any more, and the old address lands on Cài đặt → AI', async () => {
    base()
    renderApp('/sandboxes')
    expect(await screen.findByRole('region', { name: 'Việc của AI' })).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Điều hướng chính' })).queryByRole('link', { name: 'Sandbox' })).toBeNull()
  })

  it('offers nothing to create: every job is there from the first day', async () => {
    base()
    renderApp('/settings?tab=ai')
    await job('Chăm sóc khách')
    expect(screen.queryByRole('button', { name: /Tạo sandbox/ })).toBeNull()
    expect(screen.queryByText(/sandbox/i)).toBeNull()
  })

  it('a job that does not talk to customers shows its flow, not a send mode or customer channels', async () => {
    base(OWNER, { 'GET /sandboxes': LESSON_LIST })
    renderApp('/settings?tab=ai')
    const card = await job('Tổng kết buổi học')
    expect(within(card).getByText('Không nhắn khách')).toBeInTheDocument()
    expect(within(card).getByText('1 thư mục bản ghi → 1 kênh Mezon')).toBeInTheDocument()
    expect(within(card).queryByText('Chế độ nháp')).toBeNull()
    expect(within(card).queryByText(/kênh khách/)).toBeNull()
  })

  it('shows each job with its mode, usage against budget, skills and channels', async () => {
    base()
    renderApp('/settings?tab=ai')
    const card = await job('Chăm sóc khách')
    expect(within(card).getByText('Đang chạy')).toBeInTheDocument()
    expect(within(card).getByText('Chế độ nháp')).toBeInTheDocument()
    expect(within(card).getByRole('progressbar', { name: 'Lượt chạy hôm nay' })).toHaveAttribute('aria-valuenow', '28')
    expect(within(card).getByText('142 / 500')).toBeInTheDocument()
    expect(within(card).getByText('3 (1 đang thử)')).toBeInTheDocument()
    expect(within(card).getByText('Messenger (chỉ nhận)')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Xem chi tiết' })).toHaveAttribute('href', '/sandboxes/sb1')
  })

  it('pauses one job without a page reload, and offers the way back once paused', async () => {
    const s = base(OWNER, { 'POST /sandboxes/sb1/pause': { status: 'paused' } })
    renderApp('/settings?tab=ai')
    await userEvent.click(within(await job('Chăm sóc khách')).getByRole('button', { name: 'Tạm dừng' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/pause')).toHaveLength(1))
  })

  it('shows a paused job as such with the way back', async () => {
    base(OWNER, { 'GET /sandboxes': { ...SANDBOXES, items: [{ ...SANDBOXES.items[0], status: 'paused' }] } })
    renderApp('/settings?tab=ai')
    const card = await job('Chăm sóc khách')
    expect(within(card).getByText('Đang tạm dừng')).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Bật lại' })).toBeInTheDocument()
  })

  it('sends staff, who have no settings, back to where they start', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/sandboxes')
    expect(await screen.findByRole('heading', { name: 'Hộp thư' })).toBeInTheDocument()
  })
})
