import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { CONV, LIST } from '../test/fixtures'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const base = (extra: Record<string, unknown> = {}) => server({
  'GET /session': STAFF, 'GET /conversations?filter=need_human': LIST, 'GET /conversations/c1': CONV, ...extra,
})

describe('Hộp thư', () => {
  it('lists the customers who need a person, with plain badges, and opens one', async () => {
    base()
    renderApp('/inbox')
    const row = await screen.findByRole('button', { name: /Nguyễn Minh Anh/ })
    expect(within(row).getByText('Cần người')).toBeInTheDocument()
    expect(within(row).getByText('Hẹn 25/10')).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: 'Nháp của AI' })).toBeInTheDocument() // opened for us: no empty pane
    expect(screen.getByRole('complementary', { name: 'Hồ sơ khách' })).toHaveTextContent('Người quyết định')
  })

  it('shows the AI draft with its catalog sources and approves it through the single send path', async () => {
    const s = base({ 'POST /drafts/d1/action': { id: 'd1', status: 'approved' } })
    renderApp('/inbox/c1')
    const draft = await screen.findByRole('article', { name: 'Nháp của AI' })
    expect(within(draft).getByText(/THCS · 15/)).toBeInTheDocument()
    expect(within(draft).getByText('Khách đang chờ')).toBeInTheDocument()
    await userEvent.click(within(draft).getByRole('button', { name: /Duyệt/ }))
    await waitFor(() => expect(s.posted('/drafts/d1/action')).toHaveLength(1))
    expect(s.posted('/drafts/d1/action')[0]).toMatchObject({ body: { action: 'approved' }, csrf: 'csrf-token-1' })
  })

  it('sends an edited text when the person edits first, and the unedited one otherwise', async () => {
    const s = base({ 'POST /drafts/d1/action': { status: 'approved' } })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa nháp' }))
    const box = screen.getByRole('textbox', { name: 'Sửa nháp' })
    await userEvent.clear(box)
    await userEvent.type(box, 'Dạ lớp THCS có buổi tối ạ.')
    await userEvent.click(screen.getByRole('button', { name: /Duyệt/ }))
    await waitFor(() => expect(s.posted('/drafts/d1/action')).toHaveLength(1))
    expect(s.posted('/drafts/d1/action')[0].body).toEqual({ action: 'approved', edited_text: 'Dạ lớp THCS có buổi tối ạ.' })
  })

  it('explains a refusal in words and leaves the draft in place', async () => {
    base({ 'POST /drafts/d1/action': fail(409, { code: 'STALE' }) })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Duyệt/ }))
    expect(await screen.findByText(/Khách vừa nhắn thêm: nháp đã cũ/)).toBeInTheDocument()
    expect(screen.getByRole('article', { name: 'Nháp của AI' })).toBeInTheDocument()
  })

  it('never offers to send a handoff draft or one for a closed window: the person must reach the customer themselves', async () => {
    const handoff = { ...CONV, drafts: [{ ...CONV.drafts[0], needs_human: true }] }
    base({ 'GET /conversations/c1': handoff })
    renderApp('/inbox/c1')
    const d = await screen.findByRole('article', { name: 'Nháp của AI' })
    expect(within(d).queryByRole('button', { name: /Duyệt/ })).toBeNull()
    expect(within(d).getByText(/Hệ thống không tự gửi nháp này/)).toBeInTheDocument()
  })

  it('offers phone/Zalo wording for an off-channel draft', async () => {
    base({ 'GET /conversations/c1': { ...CONV, window: { open: false, basis: null, expires_at: null }, drafts: [{ ...CONV.drafts[0], route: 'offchannel' }] } })
    renderApp('/inbox/c1')
    const d = await screen.findByRole('article', { name: 'Nháp của AI' })
    expect(within(d).getByText(/gọi điện hoặc nhắn Zalo/)).toBeInTheDocument()
    expect(within(d).queryByRole('button', { name: /Duyệt/ })).toBeNull()
    expect(within(d).getByRole('button', { name: 'Đã liên hệ' })).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: /Nhập tin nhắn/ })).toBeDisabled()
  })

  it('sends a typed reply and clears the box', async () => {
    const s = base({ 'POST /conversations/c1/reply': { status: 'approved' } })
    renderApp('/inbox/c1')
    const box = await screen.findByRole('textbox', { name: /Nhập tin nhắn/ })
    await userEvent.type(box, 'Dạ em chào chị')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    await waitFor(() => expect(s.posted('/conversations/c1/reply')).toHaveLength(1))
    expect(s.posted('/conversations/c1/reply')[0].body).toEqual({ text: 'Dạ em chào chị' })
    await waitFor(() => expect(box).toHaveValue(''))
  })

  it('confirms a fact the AI only guessed, books a free seat and records an outcome', async () => {
    const s = base({ 'POST /facts/f1/confirm': { status: 'active' }, 'POST /conversations/c1/booking': { booking_id: 'b1' }, 'POST /conversations/c1/outcome': { state: 'won' } })
    renderApp('/inbox/c1')
    const side = await screen.findByRole('complementary', { name: 'Hồ sơ khách' })
    expect(within(side).getByText('Cần xác nhận')).toBeInTheDocument()
    await userEvent.click(within(side).getByRole('button', { name: 'Xác nhận' }))
    await userEvent.click(within(side).getByRole('button', { name: /Đặt/ }))
    await userEvent.click(within(side).getByRole('button', { name: 'Đã chốt' }))
    await waitFor(() => expect(s.posted('/conversations/c1/outcome')).toHaveLength(1))
    expect(s.posted('/facts/f1/confirm')).toHaveLength(1)
    expect(s.posted('/conversations/c1/booking')[0].body).toEqual({ slot_code: 'LH-A' })
    expect(s.posted('/conversations/c1/outcome')[0].body).toEqual({ status: 'won' })
  })

  it('tells the person when a seat was taken meanwhile', async () => {
    base({ 'POST /conversations/c1/booking': fail(409, { code: 'SLOT_FULL' }) })
    renderApp('/inbox/c1')
    await userEvent.click(await screen.findByRole('button', { name: /Đặt/ }))
    expect(await screen.findByText('Buổi này đã hết chỗ.')).toBeInTheDocument()
  })

  it('lets staff cancel a booking the AI made', async () => {
    const s = base({ 'GET /conversations/c1': { ...CONV, bookings: [{ id: 'b1', slot: 'LH-A', at: '2026-10-22T12:00:00Z', by_ai: true }], open_slots: [] }, 'POST /bookings/b1/cancel': { status: 'cancelled' } })
    renderApp('/inbox/c1')
    expect(await screen.findByText(/AI giữ chỗ/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Huỷ lịch' }))
    await waitFor(() => expect(s.posted('/bookings/b1/cancel')).toHaveLength(1))
  })

  it('opens the first customer on arrival, and the first of the new list when the tab changes', async () => {
    const other = { items: [{ ...LIST.items[0], id: 'c2', name: 'Trần Quốc Bảo' }], counts: LIST.counts }
    const s = base({ 'GET /conversations?filter=waiting': other, 'GET /conversations/c2': { ...CONV, id: 'c2', name: 'Trần Quốc Bảo' } })
    renderApp('/inbox')
    expect(await screen.findByRole('heading', { name: 'Nguyễn Minh Anh', level: 2 })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Đang chờ/ }))
    expect(await screen.findByRole('heading', { name: 'Trần Quốc Bảo', level: 2 })).toBeInTheDocument()
    expect(s.calls.filter((c) => c.path === '/conversations/c1')).not.toHaveLength(0)
  })

  it('does not replace a conversation that was reached by its own link', async () => {
    const other = { items: [{ ...LIST.items[0], id: 'c9', name: 'Người khác' }], counts: LIST.counts }
    const s = base({ 'GET /conversations?filter=need_human': other })
    renderApp('/inbox/c1')
    expect(await screen.findByRole('heading', { name: 'Nguyễn Minh Anh', level: 2 })).toBeInTheDocument()
    await screen.findByRole('button', { name: /Người khác/ })
    expect(s.calls.some((c) => c.path === '/conversations/c9')).toBe(false)
  })

  it('welcomes the person with the state of the inbox when there is nobody to open', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/inbox')
    expect(await screen.findByRole('heading', { name: 'Chào Khai' })).toBeInTheDocument()
    expect(await screen.findByText(/không có khách nào đang chờ/)).toBeInTheDocument()
    expect(screen.getByText('Không có khách nào cần người. Tốt lắm.')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Xem kỹ năng của AI' })).toBeInTheDocument()
  })

  it('warns on the welcome screen when the AI is paused', async () => {
    server({ 'GET /session': { ...OWNER, ai: 'paused' }, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 2, silent: 1, all: 3 } } })
    renderApp('/inbox')
    expect(await screen.findByText(/AI đang tạm dừng: khách nhắn sẽ không có nháp/)).toBeInTheDocument()
    expect(screen.getByText('Đây là tình hình hộp thư. Chọn một mục ở bên trái để bắt đầu.')).toBeInTheDocument()
  })

  it('switches list with the tabs', async () => {
    const s = base({ 'GET /conversations?filter=silent': { items: [], counts: LIST.counts } })
    renderApp('/inbox')
    await userEvent.click(await screen.findByRole('tab', { name: /Khách im/ }))
    await waitFor(() => expect(s.calls.some((c) => c.path === '/conversations?filter=silent')).toBe(true))
  })
})
