import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { SandboxDetail, SourceDetail, SourceItem, SourceList, ToolList } from '../api/types'
import { SANDBOXES } from '../test/fixtures'
import { OWNER, STAFF, renderApp, server } from '../test/harness'

const LEVELS = { read: 'Đọc', internal: 'Ghi nội bộ', customer: 'Gửi khách', external: 'Dữ liệu ngoài' } as const
const TOOLS: ToolList = {
  levels: LEVELS, counts: { tools: 2, sources: 1, channels: 1 },
  items: [
    { name: 'read_messages', label: 'Đọc tin nhắn', about: 'Đọc các tin gần nhất', level: 'read', level_label: 'Đọc', sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách', on: true }], skills: 4 },
    { name: 'book_slot', label: 'Giữ chỗ học thử', about: 'Giữ một chỗ', level: 'internal', level_label: 'Ghi nội bộ', sandboxes: [{ id: 'sb1', title: 'Chăm sóc khách', on: false }], skills: 0 },
  ],
}
const tool = (name: string, label: string, level: 'read' | 'internal', on = true) => ({ name, label, about: '', level, level_label: LEVELS[level], on, skills: [] as string[] })
const SB: SandboxDetail = {
  id: 'sb1', title: 'Chăm sóc khách', purpose: 'customer_care', about: 'Nói chuyện với khách', status: 'active', levels: LEVELS,
  facing: { customer: true, tools: true }, feeds: [], pushes: [],
  profile: { id: 'customer_drafter', version: 1, ceiling: 'Gửi khách', max_tool_calls: 4 },
  inputs: { channels: [{ kind: 'messenger', status: 'active', sends: false }], catalog_items: 38, sources: [] },
  tools: [tool('read_messages', 'Đọc tin nhắn', 'read'), tool('book_slot', 'Giữ chỗ học thử', 'internal', false)],
  send: { mode: 'manual', auto_possible: true, channels: [{ kind: 'messenger', can_send: true, problems: [] }],
    skills: [{ name: 'tra-loi-khach', can_auto: true, effective: 'manual', why: 'Đang ở chế độ duyệt tay của sandbox.' }, { name: 'hoi-lai-khach-im', can_auto: false, effective: 'manual', why: 'Soạn nháp: kỹ năng này luôn chờ nhân viên duyệt.' }] },
  skills: [
    { id: 's1', name: 'tra-loi-khach', status: 'live', source: 'system', trigger: '', uses: 1, total: 2, cells: { read_messages: 'uses', book_slot: 'blocked' } },
    { id: 's2', name: 'tuy-chinh-nhac-gia', status: 'shadow', source: 'custom', trigger: '', uses: 1, total: 2, cells: { read_messages: 'uses', book_slot: 'locked' } },
  ],
}
const SRC = (over: Partial<SourceItem> = {}): SourceItem => ({ id: 'x1', name: 'kho-hang', kind: 'http_readonly', kind_label: 'Nguồn HTTP chỉ-đọc', host: 'api.shop.example', description: '', state: 'active',
  alert: null, alert_code: null, pinned_tools: [], sandbox: { id: 'sb2', title: 'Báo cáo cho chủ' }, deleted_at: null, deleted_by: null, calls_7d: 142, errors_7d: 3, last_at: new Date().toISOString(), ...over })
const SOURCES = (items: SourceItem[]): SourceList => ({ items, counts: { all: items.filter((i) => i.state !== 'deleted').length, deleted: items.filter((i) => i.state === 'deleted').length },
  attachable: [{ id: 'sb2', title: 'Báo cáo cho chủ' }], blocked: [{ id: 'sb1', title: 'Chăm sóc khách' }] })
const DETAIL = (over: Partial<SourceDetail> = {}): SourceDetail => ({ ...SRC(), url: 'https://api.shop.example/v1/stock?sku={q}', allow_hosts: ['api.shop.example'], auth_saved: true, auth_header: null,
  pin: 'a91f…c04e', pin_ok: true, attachable: [{ id: 'sb2', title: 'Báo cáo cho chủ' }], ...over })

const LESSON_SB: SandboxDetail = {
  ...SB, id: 'sb3', title: 'Tổng kết buổi học', purpose: 'lesson_recap', about: 'Bản ghi buổi học thành tổng kết, không nhắn khách',
  facing: { customer: false, tools: false }, tools: [], profile: { id: 'lesson_recapper', version: 1, ceiling: 'Ghi nội bộ', max_tool_calls: 0 },
  inputs: { channels: [], catalog_items: 0, sources: [] }, send: { mode: 'manual', auto_possible: false, skills: [], channels: [] },
  feeds: [{ id: 'f1', kind: 'drive', label: 'Thư mục Google Drive', where: '…lLkyBxO94-y', active: true, since: '2026-10-22T02:00:00Z', noun: 'thư mục bản ghi', unit: 'buổi', lessons: { done: 2, failed: 1, waiting: 1 } }],
  pushes: [{ id: 'p1', kind: 'mezon', label: 'Mezon thật', where: 'webhook.mezon.ai', active: true }],
  skills: [{ id: 's9', name: 'tom-tat-buoi-hoc', status: 'live', source: 'system', trigger: 'Có bản ghi buổi học mới', uses: 0, total: 0, cells: {} }],
}

describe('Sandbox không nhắn khách', () => {
  it('shows what comes in and where it goes, and only the tabs that kind of sandbox has', async () => {
    server({ 'GET /session': OWNER, 'GET /sandboxes/sb3': LESSON_SB, 'GET /sandboxes': SANDBOXES })
    renderApp('/sandboxes/sb3')
    expect(await screen.findByText('Thư mục Google Drive')).toBeInTheDocument()
    expect(screen.getByText('webhook.mezon.ai')).toBeInTheDocument()
    expect(screen.getByText('Có bản ghi buổi học mới')).toBeInTheDocument()  // the same words the Skills page uses, not lesson.recorded
    expect(screen.getByText('Không dùng: AI chỉ đọc và viết')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Công cụ/ })).toBeNull()
    expect(screen.queryByRole('tab', { name: /Chế độ gửi/ })).toBeNull()
    expect(screen.queryByText(/Catalog nội bộ/)).toBeNull()
    expect(screen.queryByText(/kênh khách/)).toBeNull()
    expect(screen.getByRole('tab', { name: /Nguồn & nơi gửi/ })).toBeInTheDocument()
  })

  it('the data tab counts the lessons of each folder and says what to do when nothing is connected', async () => {
    server({ 'GET /session': OWNER, 'GET /sandboxes/sb3': { ...LESSON_SB, feeds: [], pushes: [] }, 'GET /sandboxes': SANDBOXES })
    renderApp('/sandboxes/sb3?tab=data')
    expect(await screen.findByText(/add-lesson-source/)).toBeInTheDocument()
    expect(screen.getByText(/add-notify-target/)).toBeInTheDocument()
  })

  it('a link to a tab this sandbox does not have lands on the overview', async () => {
    server({ 'GET /session': OWNER, 'GET /sandboxes/sb3': LESSON_SB, 'GET /sandboxes': SANDBOXES })
    renderApp('/sandboxes/sb3?tab=send')
    expect(await screen.findByText('Thư mục Google Drive')).toBeInTheDocument()
    expect(screen.queryByText('Chế độ gửi tin cho khách')).toBeNull()
  })
})

describe('Công cụ & kết nối', () => {
  it('lists tools with their level, where they run and how many skills use them; switched-off ones are struck', async () => {
    server({ 'GET /session': OWNER, 'GET /tools': TOOLS })
    renderApp('/tools')
    const row = (await screen.findByText('Giữ chỗ học thử')).closest('[role=row]') as HTMLElement
    expect(within(row).getByText('Ghi nội bộ')).toBeInTheDocument()
    expect(within(row).getByText('Chăm sóc khách (đã tắt)')).toBeInTheDocument()
    expect(screen.getByText('Ba mức quyền của công cụ')).toBeInTheDocument()
  })

  it('is the owner\'s page: staff do not get the menu item', async () => {
    server({ 'GET /session': STAFF, 'GET /skills': { items: [], counts: { all: 0, live: 0, shadow: 0, draft: 0, retired: 0, deleted: 0 }, min_trial_runs: 10 } })
    renderApp('/skills')
    await screen.findByText('Không có kỹ năng nào ở mục này.')
    expect(screen.queryByRole('link', { name: /Công cụ & kết nối/ })).toBeNull()
  })

  it('shows an alerted source in red with a way to review it, and locks one only after a confirmation', async () => {
    const alert = SRC({ id: 'x2', name: 'mcp-lich-hoc', kind: 'mcp', kind_label: 'MCP chỉ-đọc', state: 'alert', alert: 'Định nghĩa của công cụ đã thay đổi sau khi bạn duyệt', alert_code: 'TOOL_CHANGED', pinned_tools: ['get_schedule'] })
    const s = server({ 'GET /session': OWNER, 'GET /tools': TOOLS, 'GET /sources': SOURCES([SRC(), alert]), 'GET /sources/x1': DETAIL(), 'GET /sources/x2': DETAIL({ ...alert, kind: 'mcp' }),
      'POST /sources/x2/review': { state: 'active' }, 'POST /sources/x1/lock': { state: 'deleted' } })
    renderApp('/tools')
    await userEvent.click(await screen.findByRole('tab', { name: /Nguồn dữ liệu & MCP/ }))
    expect(await screen.findByText('Định nghĩa của công cụ đã thay đổi sau khi bạn duyệt')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /mcp-lich-hoc/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Duyệt lại định nghĩa mới' }))
    await waitFor(() => expect(s.posted('/sources/x2/review')).toHaveLength(1))
    await userEvent.click(screen.getByRole('button', { name: /kho-hang/ }))
    expect(await screen.findByText('a91f…c04e')).toBeInTheDocument()
    expect(screen.queryByText(/sk-/)).toBeNull() // the key is never on screen
    await userEvent.click(screen.getByRole('button', { name: 'Khoá nguồn này' }))
    expect(s.posted('/sources/x1/lock')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Khoá nguồn' }))
    await waitFor(() => expect(s.posted('/sources/x1/lock')).toHaveLength(1))
  })

  it('keeps locked sources in their own list with a way back', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /tools': TOOLS, 'GET /sources': SOURCES([SRC({ state: 'deleted', deleted_at: new Date().toISOString(), deleted_by: 'staff:owner' })]),
      'GET /sources/x1': DETAIL({ state: 'deleted' }), 'POST /sources/x1/unlock': { state: 'active' } })
    renderApp('/tools')
    await userEvent.click(await screen.findByRole('tab', { name: /Nguồn dữ liệu & MCP/ }))
    expect(await screen.findByText('Chưa có nguồn dữ liệu nào.', { exact: false })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Đã khoá \(1\)/ }))
    await userEvent.click(await screen.findByRole('button', { name: /kho-hang/ }))
    await userEvent.click(await screen.findByRole('button', { name: /Khôi phục nguồn này/ }))
    await waitFor(() => expect(s.posted('/sources/x1/unlock')).toHaveLength(1))
  })
})

describe('Thêm nguồn dữ liệu', () => {
  it('pins an HTTP source: needs {q}, offers only sandboxes without customers, sends the key once', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /sources': SOURCES([]), 'POST /sources': { id: 'x9' }, 'GET /tools': TOOLS })
    renderApp('/tools/sources/new')
    const save = await screen.findByRole('button', { name: /Ghim và thêm nguồn/ })
    expect(save).toBeDisabled()
    expect(screen.getByText(/Có nói chuyện với khách: không gắn được/)).toBeInTheDocument()
    await userEvent.type(screen.getByPlaceholderText('kho-hang'), 'kho-hang')
    await userEvent.type(screen.getByPlaceholderText('https://api.shop.example/v1/stock?sku={q}'), 'https://api.shop.example/v1/stock?sku=abc')
    expect(save).toBeDisabled() // no {q}
    await userEvent.clear(screen.getByPlaceholderText('https://api.shop.example/v1/stock?sku={q}'))
    await userEvent.type(screen.getByPlaceholderText('https://api.shop.example/v1/stock?sku={q}'), 'https://api.shop.example/v1/stock?sku=')
    await userEvent.paste('{q}')
    await userEvent.type(screen.getByPlaceholderText('••••••••••••'), 'sk-123')
    await userEvent.click(save)
    await waitFor(() => expect(s.posted('/sources')).toHaveLength(1))
    expect(s.posted('/sources')[0].body).toMatchObject({ kind: 'http_readonly', name: 'kho-hang', host: 'api.shop.example', sandbox_id: 'sb2', secret: 'sk-123' })
  })

  it('shows what an MCP server offers and will not let a writing tool be chosen', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /sources': SOURCES([]), 'GET /tools': TOOLS, 'POST /sources': { id: 'x9' },
      'POST /sources/mcp/describe': { tools: [{ name: 'get_schedule', description: 'Lịch học của một lớp', read_only: true }, { name: 'update_schedule', description: 'Đổi lịch học', read_only: false }] } })
    renderApp('/tools/sources/new')
    await userEvent.click(await screen.findByRole('radio', { name: /MCP server/ }))
    await userEvent.type(screen.getByPlaceholderText('kho-hang'), 'mcp-lich-hoc')
    await userEvent.type(screen.getByPlaceholderText('https://mcp.lms.example/mcp'), 'https://mcp.lms.example/mcp')
    await userEvent.click(screen.getByRole('button', { name: 'Đọc định nghĩa từ máy chủ' }))
    expect(await screen.findByRole('radio', { name: /update_schedule/ })).toBeDisabled()
    expect(screen.getByText(/Có ghi, không gắn được/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /get_schedule/ }))
    await userEvent.click(screen.getByRole('button', { name: /Ghim và thêm nguồn/ }))
    await waitFor(() => expect(s.posted('/sources')).toHaveLength(1))
    expect(s.posted('/sources')[0].body).toMatchObject({ kind: 'mcp', tool: 'get_schedule', host: 'mcp.lms.example' })
  })
})

describe('Chi tiết sandbox', () => {
  it('draws inputs, the sandbox and its skills with how many tools each uses', async () => {
    server({ 'GET /session': OWNER, 'GET /sandboxes/sb1': SB, 'GET /sandboxes': SANDBOXES })
    renderApp('/sandboxes/sb1')
    expect(await screen.findByText(/AI chỉ dùng được công cụ nằm trong cả hai danh sách/)).toBeInTheDocument()
    expect(screen.getByText('38 mục: khoá, giá, lịch học thử')).toBeInTheDocument()
    expect(screen.getByText(/customer_drafter · bản 1/)).toBeInTheDocument()
    expect(screen.getAllByText(/Dùng 1\/2 công cụ/)).toHaveLength(2)
  })

  it('shows the permission matrix and switches a tool for this sandbox, owner only', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /sandboxes/sb1': SB, 'GET /sandboxes': SANDBOXES, 'POST /sandboxes/sb1/tools/book_slot/on': { tool: 'book_slot', on: true },
      'GET /sandboxes/sb1/tools/book_slot': { ...SB.tools[1], sandbox: 'Chăm sóc khách', safety: ['Chỗ được khoá, không vượt sức chứa'], if_off: null } })
    renderApp('/sandboxes/sb1?tab=tools')
    expect(await screen.findByRole('img', { name: 'tra-loi-khach · Giữ chỗ học thử: Kỹ năng cần nhưng sandbox đã tắt' })).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'tuy-chinh-nhac-gia · Giữ chỗ học thử: Bị khoá với kỹ năng từ form' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Giữ chỗ học thử' }))
    const sw = await screen.findByRole('switch', { name: 'Cho phép dùng' })
    expect(sw).not.toBeChecked()
    await userEvent.click(sw)
    await waitFor(() => expect(s.posted('/sandboxes/sb1/tools/book_slot/on')).toHaveLength(1))
  })
})

describe('Chế độ gửi', () => {
  it('shows manual by default, which skills could ever send alone, and asks before turning auto on', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /sandboxes/sb1': SB, 'GET /sandboxes': SANDBOXES, 'POST /sandboxes/sb1/send-mode': { send_mode: 'auto', changed: true } })
    renderApp('/sandboxes/sb1?tab=send')
    expect(await screen.findByRole('radio', { name: /Duyệt tay/, checked: true })).toBeInTheDocument()
    expect(screen.getByText('Soạn nháp: kỹ năng này luôn chờ nhân viên duyệt.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /Tự gửi khi đủ điều kiện/ }))
    expect(s.posted('/sandboxes/sb1/send-mode')).toHaveLength(0) // a question first
    const group = screen.getByRole('group', { name: 'Xác nhận bật tự gửi' })
    expect(within(group).getByText(/không ai duyệt/)).toBeInTheDocument()
    await userEvent.click(within(group).getByRole('button', { name: 'Bật tự gửi' }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/send-mode')[0].body).toEqual({ mode: 'auto' }))
  })

  it('goes back to manual in one click, and warns when no channel could send anyway', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /sandboxes': SANDBOXES, 'POST /sandboxes/sb1/send-mode': { send_mode: 'manual', changed: true },
      'GET /sandboxes/sb1': { ...SB, send: { ...SB.send, mode: 'auto', auto_possible: false, channels: [{ kind: 'messenger', can_send: false, problems: ['Kênh chưa bật gửi từ hệ thống'] }] } } })
    renderApp('/sandboxes/sb1?tab=send')
    expect(await screen.findByText('Kênh chưa bật gửi từ hệ thống')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: /Duyệt tay/ }))
    await waitFor(() => expect(s.posted('/sandboxes/sb1/send-mode')[0].body).toEqual({ mode: 'manual' }))
  })
})
