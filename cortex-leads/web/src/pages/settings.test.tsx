import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { AiOverview, BusinessSettings, Channels, NotifyTargets } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const BIZ: BusinessSettings = { name: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', hours: { start: '08:00', end: '21:00' }, hours_differ: false, ai_name: null, disclosure: 'Trợ lý AI của Trung tâm Minh Khai' }
const NOTIFY: NotifyTargets = { telegram_ready: true, sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách' }],
  items: [{ id: 't1', kind: 'telegram', address: '…7890', label: 'Nhóm tư vấn', sandbox_id: null, sandbox: null, created_at: '2026-10-20T01:00:00Z' },
    { id: 't2', kind: 'mezon', address: 'webhook.mezon.ai/…', label: null, sandbox_id: 'sb1', sandbox: 'Chăm sóc khách', created_at: '2026-10-20T01:00:00Z' }] }
const TWO = [{ id: 'sb1', title: 'Chăm sóc khách' }, { id: 'sb2', title: 'Hỗ trợ học viên' }]
const TWO_NOTIFY: NotifyTargets = { ...NOTIFY, sandboxes: TWO }
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
    await userEvent.type(screen.getByLabelText(/Tên trợ lý AI/), 'Mai')
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
    await userEvent.type(await screen.findByLabelText(/Tên trợ lý AI/), 'Mai')
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
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': TWO_NOTIFY, 'POST /settings/notify-targets': { id: 't3' } })
    renderApp('/settings?tab=notify')
    await userEvent.type(await screen.findByPlaceholderText('-1001234567890'), '-100555666')
    await userEvent.selectOptions(screen.getByLabelText('Nhận tin của'), 'sb1')
    await userEvent.click(screen.getByRole('button', { name: /Thêm$/ }))
    await waitFor(() => expect(s.posted('/settings/notify-targets')[0].body).toEqual({ kind: 'telegram', address: '-100555666', sandbox_id: 'sb1' }))
    await waitFor(() => expect(screen.getByPlaceholderText('-1001234567890')).toHaveValue(''))
  })

  it('does not ask which sandbox when there is only one: the target is for the whole business', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': NOTIFY, 'POST /settings/notify-targets': { id: 't3' } })
    renderApp('/settings?tab=notify')
    await userEvent.type(await screen.findByPlaceholderText('-1001234567890'), '-100555666')
    expect(screen.queryByLabelText('Nhận tin của')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Thêm$/ }))
    await waitFor(() => expect(s.posted('/settings/notify-targets')[0].body).toEqual({ kind: 'telegram', address: '-100555666', sandbox_id: null }))
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

  it('offers only Mezon when the server has no Telegram bot, names no server setting, and shows a refused address', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/notify-targets': { ...NOTIFY, telegram_ready: false, items: [] },
      'POST /settings/notify-targets': fail(422, { code: 'BAD_ADDRESS', message: 'Địa chỉ webhook không dùng được: cần https.' }) })
    renderApp('/settings?tab=notify')
    await userEvent.type(await screen.findByPlaceholderText('https://webhook.mezon.ai/…'), 'abc')
    expect(screen.queryByText(/Telegram/)).toBeNull()
    expect(screen.queryByText(/CL_/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Thêm$/ }))
    expect(await screen.findByText(/cần https/)).toBeInTheDocument()
    expect(s.posted('/settings/notify-targets')[0].body).toMatchObject({ kind: 'mezon', address: 'abc' })
  })
})

describe('Kênh nhắn tin', () => {
  it('does not ask which sandbox when there is only one, and says where the messages will go', async () => {
    server({ 'GET /session': OWNER, 'GET /settings/channels': CHANNELS })
    renderApp('/settings?tab=channels')
    expect(await screen.findByText(/Tin của khách sẽ đi vào «Chăm sóc khách»/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Đưa tin vào')).toBeNull()
  })

  it('asks which sandbox from two on, and sends the one chosen', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/channels': { ...CHANNELS, sandboxes: TWO }, 'POST /settings/channels': { id: 'conn_n', kind: 'messenger', secret: 'x', ingest_url: null } })
    renderApp('/settings?tab=channels')
    await userEvent.selectOptions(await screen.findByLabelText('Đưa tin vào'), 'sb2')
    await userEvent.click(screen.getByRole('button', { name: /Tạo kênh/ }))
    await waitFor(() => expect(s.posted('/settings/channels')[0].body).toEqual({ kind: 'messenger', sandbox_id: 'sb2' }))
  })

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
    expect(await screen.findByText(/Thiếu việc «Chăm sóc khách» của AI/)).toBeInTheDocument()
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
    expect(s.posted('/sandboxes/sb1/send-mode')).toHaveLength(0) // a question first: this is the only place that writes the mode
    const group = screen.getByRole('group', { name: 'Xác nhận bật tự gửi' })
    expect(within(group).getByText(/không ai duyệt/)).toBeInTheDocument()
    await userEvent.click(within(group).getByRole('button', { name: 'Không' }))
    expect(s.posted('/sandboxes/sb1/send-mode')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Tự gửi' }))
    await userEvent.click(within(screen.getByRole('group', { name: 'Xác nhận bật tự gửi' })).getByRole('button', { name: 'Bật tự gửi' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/send-mode')[0].body).toEqual({ mode: 'auto' }))
  })

  it('goes back to manual in one click, with no question', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/ai': { ...AI, sandboxes: [{ ...AI.sandboxes[0], send_mode: 'auto' }] }, 'POST /sandboxes/sb1/send-mode': { send_mode: 'manual', changed: true } })
    renderApp('/settings?tab=ai')
    await userEvent.click(await screen.findByRole('button', { name: 'Duyệt tay' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/send-mode')[0].body).toEqual({ mode: 'manual' }))
  })

  it('stops the AI with the existing kill switch', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /settings/ai': AI, 'POST /kill-switch': { changed: 1 } })
    renderApp('/settings?tab=ai')
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng AI' }))
    await waitFor(() => expect(s.posted('/kill-switch')[0].body).toEqual({ paused: true }))
  })
})

describe('no Bắt đầu page', () => {
  it('has no Bắt đầu in the menu, and its old address goes where the person starts', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/start')
    expect(await screen.findByRole('heading', { name: 'Hộp thư' })).toBeInTheDocument()
    expect(within(screen.getByRole('navigation', { name: 'Điều hướng chính' })).queryByRole('link', { name: 'Bắt đầu' })).toBeNull()
  })
})
