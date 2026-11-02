import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { AiOverview, BusinessSettings, Channels, NotifyTargets, Onboarding } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const BIZ: BusinessSettings = { name: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', hours: { start: '08:00', end: '21:00' }, hours_differ: false, ai_name: null, disclosure: 'Trợ lý AI của Trung tâm Minh Khai' }
const NOTIFY: NotifyTargets = { telegram_ready: true, sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách' }],
  items: [{ id: 't1', kind: 'telegram', address: '…7890', label: 'Nhóm tư vấn', sandbox_id: null, sandbox: null, created_at: '2026-10-20T01:00:00Z' },
    { id: 't2', kind: 'mezon', address: 'webhook.mezon.ai/…', label: null, sandbox_id: 'sb1', sandbox: 'Chăm sóc khách', created_at: '2026-10-20T01:00:00Z' }] }
const CHANNELS: Channels = { kinds: ['messenger', 'web', 'zalo_oa'], ingest_url: 'https://cortex.example.vn/ingest/v1/events', sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách' }],
  items: [{ id: 'conn_abc', kind: 'messenger', status: 'active', sandbox: 'Chăm sóc khách', sandbox_id: 'sb1', sends: false, created_at: '2026-10-20T01:00:00Z', last_event_at: null }] }
const AI: AiOverview = { disclosure: 'Trợ lý AI của Trung tâm Minh Khai', sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách', send_mode: 'manual', status: 'active',
  skills: [{ name: 'hoi-lai-khach-im', status: 'live', sends: false }], never_say: ['cam kết đậu'], must_handoff: ['hoàn tiền'] }] }

describe('Cài đặt', () => {
  it('is the owner\'s page only: staff get no menu item and are sent back to the inbox', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/settings')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: 'Cài đặt' })).toBeNull()
    expect(screen.queryByRole('tab', { name: 'Doanh nghiệp' })).toBeNull()
  })

  it('opens on the business profile and moves between the tabs by the address', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/business': BIZ, 'GET /settings/channels': CHANNELS })
    renderApp('/settings')
    expect(await screen.findByDisplayValue('Trung tâm Minh Khai')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Kênh nhắn tin' }))
    expect(await screen.findByText('conn_abc')).toBeInTheDocument()
  })

  it('opens the Google tab when Google sends the person back with a result and no tab', async () => {
    server({ 'GET /session': OWNER, 'GET /google/accounts': { configured: true, items: [], sources: [], kinds: [], sandboxes: [] } })
    renderApp('/settings?error=DENIED')
    expect(await screen.findByText(/không đồng ý cấp quyền/)).toBeInTheDocument()
  })
})

describe('Hồ sơ doanh nghiệp', () => {
  it('shows the line a customer will read as the AI name is typed, and saves what the form holds', async () => {
    const saved = { ...BIZ, ai_name: 'Mai', disclosure: 'Trợ lý AI Mai của Trung tâm Minh Khai', hours: { start: '07:30', end: '20:00' } }
    const s = server({ 'GET /session': OWNER, 'GET /settings/business': BIZ, 'PUT /settings/business': saved })
    renderApp('/settings')
    await screen.findByDisplayValue('Trung tâm Minh Khai')
    expect(screen.getByTestId('disclosure')).toHaveTextContent('Trợ lý AI của Trung tâm Minh Khai')
    await userEvent.type(screen.getByLabelText(/Tên của trợ lý AI/), 'Mai')
    expect(screen.getByTestId('disclosure')).toHaveTextContent('Trợ lý AI Mai của Trung tâm Minh Khai')
    await userEvent.clear(screen.getByLabelText('Giờ mở cửa')); await userEvent.type(screen.getByLabelText('Giờ mở cửa'), '07:30')
    await userEvent.clear(screen.getByLabelText('Giờ đóng cửa')); await userEvent.type(screen.getByLabelText('Giờ đóng cửa'), '20:00')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PUT')?.body).toEqual({ name: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', hours: { start: '07:30', end: '20:00' }, ai_name: 'Mai' }))
    expect(await screen.findByText('Đã lưu.')).toBeInTheDocument()
    expect(s.calls.find((c) => c.method === 'PUT')?.csrf).toBe('csrf-token-1')
  })

  it('will not send hours that close before they open, and says why', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/business': BIZ })
    renderApp('/settings')
    await screen.findByDisplayValue('Trung tâm Minh Khai')
    await userEvent.clear(screen.getByLabelText('Giờ đóng cửa')); await userEvent.type(screen.getByLabelText('Giờ đóng cửa'), '07:00')
    expect(screen.getByRole('alert')).toHaveTextContent('Giờ đóng cửa phải sau giờ mở cửa')
    expect(screen.getByRole('button', { name: 'Lưu thay đổi' })).toBeDisabled()
    expect(s.calls.some((c) => c.method === 'PUT')).toBe(false)
  })

  it('shows the server\'s refusal in words', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/business': BIZ, 'PUT /settings/business': fail(422, { code: 'BAD_TIMEZONE', message: 'Múi giờ không hợp lệ (ví dụ Asia/Ho_Chi_Minh).' }) })
    renderApp('/settings')
    await userEvent.type(await screen.findByLabelText(/Tên của trợ lý AI/), 'Mai')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
    expect(await screen.findByText(/Múi giờ không hợp lệ/)).toBeInTheDocument()
  })

  it('warns that saving will set the same hours on sandboxes that had different ones', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/business': { ...BIZ, hours_differ: true } })
    renderApp('/settings')
    expect(await screen.findByText(/giờ khác nhau/)).toBeInTheDocument()
  })
})

describe('Thông báo', () => {
  it('lists destinations masked, with a test button that says whether it arrived', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': NOTIFY, 'POST /settings/notify-targets/t1/test': { ok: true }, 'POST /settings/notify-targets/t2/test': { ok: false } })
    renderApp('/settings?tab=notify')
    const rows = await screen.findAllByRole('row')
    expect(within(rows[0]).getByText('…7890')).toBeInTheDocument()
    expect(within(rows[1]).getByText('webhook.mezon.ai/…')).toBeInTheDocument()
    await userEvent.click(within(rows[0]).getByRole('button', { name: /Gửi thử/ }))
    expect(await within(rows[0]).findByRole('status')).toHaveTextContent('Đã gửi')
    await userEvent.click(within(rows[1]).getByRole('button', { name: /Gửi thử/ }))
    expect(await within(rows[1]).findByRole('alert')).toHaveTextContent('Không gửi được')
    expect(s.posted('/settings/notify-targets/t1/test')).toHaveLength(1)
  })

  it('adds a destination bound to a sandbox and empties the address box afterwards', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': NOTIFY, 'POST /settings/notify-targets': { id: 't3' } })
    renderApp('/settings?tab=notify')
    await userEvent.type(await screen.findByPlaceholderText('-1001234567890'), '-100555666')
    await userEvent.selectOptions(screen.getByLabelText('Nhận tin của'), 'sb1')
    await userEvent.click(screen.getByRole('button', { name: /Thêm$/ }))
    await waitFor(() => expect(s.posted('/settings/notify-targets')[0].body).toEqual({ kind: 'telegram', address: '-100555666', sandbox_id: 'sb1' }))
    await waitFor(() => expect(screen.getByPlaceholderText('-1001234567890')).toHaveValue(''))
  })

  it('asks before it drops a destination', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': NOTIFY, 'DELETE /settings/notify-targets/t1': { status: 'ok' } })
    renderApp('/settings?tab=notify')
    const row = (await screen.findAllByRole('row'))[0]
    await userEvent.click(within(row).getByRole('button', { name: 'Bỏ' }))
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(row).getByRole('button', { name: 'Bỏ' }))
    await waitFor(() => expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1))
  })

  it('says so when the server has no Telegram bot, and shows a refused address', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/notify-targets': { ...NOTIFY, telegram_ready: false, items: [] },
      'POST /settings/notify-targets': fail(422, { code: 'BAD_ADDRESS', message: 'Địa chỉ webhook không dùng được: cần https.' }) })
    renderApp('/settings?tab=notify')
    expect(await screen.findByText(/CL_TELEGRAM_BOT_TOKEN/)).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('-1001234567890'), 'abc')
    await userEvent.click(screen.getByRole('button', { name: /Thêm$/ }))
    expect(await screen.findByText(/cần https/)).toBeInTheDocument()
  })
})

describe('Kênh nhắn tin', () => {
  it('shows the secret once, in the bridge settings, and not again after it is closed', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/channels': CHANNELS, 'POST /settings/channels': { id: 'conn_new', kind: 'messenger', secret: 'S3CRET-VALUE-xyz', ingest_url: CHANNELS.ingest_url } })
    renderApp('/settings?tab=channels')
    await userEvent.click(await screen.findByRole('button', { name: /Tạo kênh/ }))
    const cfg = await screen.findByLabelText('Cấu hình bridge')
    expect(cfg).toHaveTextContent('CL_CONNECTOR_ID=conn_new')
    expect(cfg).toHaveTextContent('CL_CONNECTOR_SECRET=S3CRET-VALUE-xyz')
    expect(cfg).toHaveTextContent('CL_INGEST_URL=https://cortex.example.vn/ingest/v1/events')
    expect(s.posted('/settings/channels')[0].body).toEqual({ kind: 'messenger', sandbox_id: 'sb1' })
    await userEvent.click(screen.getByRole('button', { name: 'Đã lưu, đóng' }))
    expect(screen.queryByText(/S3CRET-VALUE-xyz/)).toBeNull()
  })

  it('shows when a channel last received a message and asks before switching it off', async () => {
    const s = server({ 'GET /session': OWNER, 'DELETE /settings/channels/conn_abc': { status: 'ok' },
      'GET /settings/channels': { ...CHANNELS, items: [{ ...CHANNELS.items[0], last_event_at: new Date().toISOString() }] } })
    renderApp('/settings?tab=channels')
    const row = (await screen.findAllByRole('row'))[0]
    expect(within(row).getByText(/Tin gần nhất/)).toBeInTheDocument()
    await userEvent.click(within(row).getByRole('button', { name: 'Tắt kênh' }))
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(within(row).getByRole('button', { name: 'Tắt' }))
    await waitFor(() => expect(s.calls.filter((c) => c.method === 'DELETE')).toHaveLength(1))
  })

  it('sends the person to create a sandbox first when there is none', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/channels': { ...CHANNELS, items: [], sandboxes: [] } })
    renderApp('/settings?tab=channels')
    expect(await screen.findByText(/Cần có một sandbox/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Tạo kênh/ })).toBeDisabled()
  })
})

describe('AI', () => {
  it('gathers the send mode, the emergency stop and what the skills forbid, and changes the mode through the existing endpoint', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/ai': AI, 'POST /sandboxes/sb1/send-mode': { send_mode: 'auto', changed: true } })
    renderApp('/settings?tab=ai')
    expect(await screen.findByText('cam kết đậu')).toBeInTheDocument()
    expect(screen.getByText('hoàn tiền')).toBeInTheDocument()
    expect(screen.getByText(/Trợ lý AI của Trung tâm Minh Khai/, { selector: 'b' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Duyệt tay' })).toHaveAttribute('aria-pressed', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Tự gửi' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/send-mode')[0].body).toEqual({ mode: 'auto' }))
  })

  it('stops the AI with the existing kill switch', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/ai': AI, 'POST /kill-switch': { changed: 1 } })
    renderApp('/settings?tab=ai')
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng AI' }))
    await waitFor(() => expect(s.posted('/kill-switch')[0].body).toEqual({ paused: true }))
  })
})

describe('Bắt đầu', () => {
  const STEPS: Onboarding = { complete: false, done: 1, steps: [
    { id: 'channel', title: 'Nối kênh nhắn tin', done: true, count: 1, href: '/settings?tab=channels', hint: 'Tạo kênh.' },
    { id: 'catalog', title: 'Nhập bảng giá và lịch học', done: false, count: 0, href: null, hint: 'Nhập bằng lệnh `cli import-catalog` hoặc màn catalog (sẽ có sau).' },
    { id: 'skills', title: 'Bật kỹ năng trả lời', done: false, count: 0, href: '/skills', hint: 'Chạy thử rồi bật.' },
    { id: 'first_draft', title: 'Có hội thoại và nháp đầu tiên', done: false, count: 0, href: '/inbox', hint: 'Nhắn thử.' }] }

  it('marks what is done and links each undone step to its screen', async () => {
    server({ 'GET /session': OWNER, 'GET /onboarding': STEPS })
    renderApp('/start')
    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(4)
    expect(within(items[0]).getByLabelText('Đã xong')).toBeInTheDocument()
    expect(within(items[2]).getByRole('link', { name: 'Làm bước này' })).toHaveAttribute('href', '/skills')
    expect(within(items[1]).queryByRole('link')).toBeNull() // the catalog has no screen yet: the hint says what to do instead
    expect(within(items[1]).getByText(/cli import-catalog/)).toBeInTheDocument()
  })

  it('says it is complete only when every step is', async () => {
    server({ 'GET /session': OWNER, 'GET /onboarding': { ...STEPS, complete: true, done: 4, steps: STEPS.steps.map((x) => ({ ...x, done: true })) } })
    renderApp('/start')
    expect(await screen.findByText(/Đã đủ bốn bước/)).toBeInTheDocument()
  })
})
