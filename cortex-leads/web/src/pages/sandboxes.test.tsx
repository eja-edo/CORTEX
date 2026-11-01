import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SANDBOXES } from '../test/fixtures'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const base = (me = OWNER, extra: Record<string, unknown> = {}) => server({ 'GET /session': me, 'GET /sandboxes': SANDBOXES, ...extra })

const LESSON_LIST = {
  ...SANDBOXES,
  items: [...SANDBOXES.items, { id: 'sb3', title: 'Tổng kết buổi học', purpose: 'lesson_recap', about: 'Bản ghi buổi học thành tổng kết, không nhắn khách', status: 'active' as const,
    send_mode: 'manual' as const, customer_facing: false, flow: '1 thư mục bản ghi → 1 kênh Mezon', budget: { runs_per_day: 200, tokens_per_day: 500_000, drafts_per_staff_per_day: 20 },
    usage: { runs: 4, tokens: 76_578 }, skills: { live: 1, shadow: 0 }, channels: [] }],
}

describe('Sandbox', () => {
  it('a sandbox that does not talk to customers shows its flow, not a send mode or customer channels', async () => {
    server({ 'GET /session': OWNER, 'GET /sandboxes': LESSON_LIST })
    renderApp('/sandboxes')
    const card = (await screen.findByRole('heading', { name: 'Tổng kết buổi học', level: 2 })).closest('section')!
    expect(within(card).getByText('Không nhắn khách')).toBeInTheDocument()
    expect(within(card).getByText('1 thư mục bản ghi → 1 kênh Mezon')).toBeInTheDocument()
    expect(within(card).queryByText('Chế độ nháp')).toBeNull()
    expect(within(card).queryByText(/kênh khách/)).toBeNull()
    expect(within(card).queryByRole('link', { name: 'Đổi chế độ gửi' })).toBeNull()
  })

  it('shows each sandbox with its mode, usage against budget, skills and channels', async () => {
    base()
    renderApp('/sandboxes')
    const card = (await screen.findByRole('heading', { name: 'Chăm sóc khách', level: 2 })).closest('section')!
    expect(within(card).getByText('Đang chạy')).toBeInTheDocument()
    expect(within(card).getByText('Chế độ nháp')).toBeInTheDocument()
    expect(within(card).getByRole('progressbar', { name: 'Lượt chạy hôm nay' })).toHaveAttribute('aria-valuenow', '28')
    expect(within(card).getByText('142 / 500')).toBeInTheDocument()
    expect(within(card).getByText('3 (1 đang thử)')).toBeInTheDocument()
    expect(within(card).getByText('Messenger (chỉ nhận)')).toBeInTheDocument()
  })

  it('offers the templates, with the unopened one visibly unavailable and not selectable', async () => {
    base()
    renderApp('/sandboxes')
    const student = await screen.findByRole('radio', { name: /Hỗ trợ học viên/ })
    expect(student).toHaveAttribute('aria-disabled', 'true')
    expect(within(student).getByText(/chờ trung tâm xác nhận nhu cầu/)).toBeInTheDocument()
    await userEvent.click(student)
    expect(screen.getByRole('radio', { name: /Chăm sóc khách/, checked: true })).toBeInTheDocument() // the click changed nothing
  })

  it('creates a sandbox from a template and a name', async () => {
    const s = base(OWNER, { 'POST /sandboxes': { id: 'sb2', name: 'customer_care-2' } })
    renderApp('/sandboxes')
    expect(await screen.findByRole('button', { name: 'Tạo sandbox' })).toBeDisabled() // no name yet
    await userEvent.type(await screen.findByPlaceholderText('Chăm sóc khách – cơ sở 2'), 'Cơ sở Cầu Giấy')
    await userEvent.click(screen.getByRole('radio', { name: /Báo cáo cho chủ/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Tạo sandbox' }))
    await waitFor(() => expect(s.posted('/sandboxes')).toHaveLength(1))
    expect(s.posted('/sandboxes')[0]).toMatchObject({ body: { template: 'owner_digest', title: 'Cơ sở Cầu Giấy' }, csrf: 'csrf-token-1' })
    expect(await screen.findByText(/Đã tạo sandbox “Cơ sở Cầu Giấy”/)).toBeInTheDocument()
  })

  it('pauses one sandbox without a page reload and shows why a creation failed', async () => {
    const s = base(OWNER, { 'POST /sandboxes/sb1/pause': { status: 'paused' }, 'POST /sandboxes': fail(422, { code: 'NOT_AVAILABLE' }) })
    renderApp('/sandboxes')
    await userEvent.click(await screen.findByRole('button', { name: 'Tạm dừng sandbox' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/pause')).toHaveLength(1))
    await userEvent.type(screen.getByPlaceholderText('Chăm sóc khách – cơ sở 2'), 'Cơ sở 3')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo sandbox' }))
    expect(await screen.findByText('Mẫu này chưa mở.')).toBeInTheDocument()
  })

  it('gives staff the list and nothing that changes it', async () => {
    base(STAFF)
    renderApp('/sandboxes')
    await screen.findByRole('heading', { name: 'Chăm sóc khách', level: 2 })
    expect(screen.queryByRole('button', { name: 'Tạm dừng sandbox' })).toBeNull()
    expect(screen.getByText('Chỉ chủ mới tạo được sandbox mới.')).toBeInTheDocument()
  })

  it('shows a paused sandbox as such with the way back', async () => {
    base(OWNER, { 'GET /sandboxes': { ...SANDBOXES, items: [{ ...SANDBOXES.items[0], status: 'paused' }] } })
    renderApp('/sandboxes')
    expect(await screen.findByText('Đang tạm dừng')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bật lại sandbox' })).toBeInTheDocument()
  })

  it('invites the owner to create the first sandbox when there is none', async () => {
    base(OWNER, { 'GET /sandboxes': { ...SANDBOXES, items: [] } })
    renderApp('/sandboxes')
    expect(await screen.findByText(/Chưa có sandbox nào/)).toBeInTheDocument()
  })
})
