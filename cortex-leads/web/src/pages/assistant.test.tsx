import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const PROPOSALS = { items: [
  { id: 'p1', kind: 'tune_skill', signal: 'nhân viên bỏ nhiều nháp', sandbox: 'Chăm sóc khách', skill: 'hoi-lai-khach-im', change: { field: 'limits.max_touches', from: 3, to: 2 }, action: 'Thử bản mới của kỹ năng (chạy thử, chưa bật)', evidence: ['nháp đã xử lý: 5', 'bị bỏ: 4'], danger: false },
  { id: 'p2', kind: 'pause_sandbox', signal: 'lỗi liên tiếp', sandbox: 'Chăm sóc khách', skill: 'tra-loi-khach', change: null, action: 'Tạm dừng AI của sandbox này', evidence: ['lỗi liên tiếp: 3'], danger: true },
] }
const base = (extra: Record<string, unknown> = {}) => server({ 'GET /session': OWNER, 'GET /proposals': PROPOSALS, ...extra })

describe('AI tổng', () => {
  it('says up front that it reads numbers only, and invites a question', async () => {
    base()
    renderApp('/assistant')
    expect(await screen.findByText(/Chỉ đọc số liệu · không đọc nội dung tin nhắn/)).toBeInTheDocument()
    expect(screen.getByText(/Hỏi AI tổng về số liệu/)).toBeInTheDocument()
  })

  it('sends the question with the conversation so far and shows the answer', async () => {
    const s = base({ 'POST /assistant/chat': { reply: 'Kỹ năng tra-loi-khach có 8 lượt bị chặn (27%).', refused: false, verified: true } })
    renderApp('/assistant')
    await userEvent.type(await screen.findByLabelText('Hỏi AI tổng'), 'Kỹ năng nào bị chặn nhiều nhất?')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    expect(await screen.findByText(/8 lượt bị chặn \(27%\)/)).toBeInTheDocument()
    expect(s.posted('/assistant/chat')[0]).toMatchObject({ body: { messages: [{ role: 'user', content: 'Kỹ năng nào bị chặn nhiều nhất?' }] }, csrf: 'csrf-token-1' })
    await userEvent.type(screen.getByLabelText('Hỏi AI tổng'), 'Còn tuần trước?')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    await waitFor(() => expect(s.posted('/assistant/chat')).toHaveLength(2))
    expect((s.posted('/assistant/chat')[1].body as { messages: unknown[] }).messages).toHaveLength(3) // question, answer, question
  })

  it('answers a click on a suggestion as if it had been typed', async () => {
    const s = base({ 'POST /assistant/chat': { reply: 'Có 12 khách đang bị bỏ rơi.', refused: false, verified: true } })
    renderApp('/assistant')
    await userEvent.click(await screen.findByRole('button', { name: 'Có bao nhiêu khách đang bị bỏ rơi?' }))
    expect(await screen.findByText('Có 12 khách đang bị bỏ rơi.')).toBeInTheDocument()
    expect(s.posted('/assistant/chat')).toHaveLength(1)
  })

  it('shows a refusal as a refusal, with the way to the inbox, and flags an answer it could not verify', async () => {
    base({ 'POST /assistant/chat': { reply: 'Mình không đọc được nội dung tin nhắn của khách.', refused: true, verified: true } })
    renderApp('/assistant')
    await userEvent.type(await screen.findByLabelText('Hỏi AI tổng'), 'Khách A đã nói gì?')
    await userEvent.click(screen.getByRole('button', { name: 'Gửi' }))
    expect(await screen.findByRole('link', { name: 'Mở trong Hộp thư' })).toHaveAttribute('href', '/inbox')
  })

  it('warns when an answer carried no verifiable figures', async () => {
    base({ 'POST /assistant/chat': { reply: 'Mình chưa trả lời chắc chắn được câu này từ số liệu hiện có.', refused: false, verified: false } })
    renderApp('/assistant')
    await userEvent.click(await screen.findByRole('button', { name: 'Nhân viên bỏ bao nhiêu nháp?' }))
    expect(await screen.findByText('Câu này chưa có số liệu để kiểm chứng.')).toBeInTheDocument()
  })

  it('explains why the chat is not available instead of failing silently', async () => {
    base({ 'POST /assistant/chat': fail(409, { code: 'NO_DIGEST_SANDBOX' }) })
    renderApp('/assistant')
    await userEvent.click(await screen.findByRole('button', { name: 'Kỹ năng nào nên tắt?' }))
    expect(await screen.findByText(/Cần tạo sandbox "Báo cáo cho chủ"/)).toBeInTheDocument()
  })

  it('does not send an empty question', async () => {
    const s = base()
    renderApp('/assistant')
    await screen.findByLabelText('Hỏi AI tổng')
    expect(screen.getByRole('button', { name: 'Gửi' })).toBeDisabled()
    expect(s.posted('/assistant/chat')).toHaveLength(0)
  })

  it('lists the proposals with their one structured change, and acts only when the owner decides', async () => {
    const s = base({ 'POST /proposals/p1/accept': { status: 'accepted' }, 'POST /proposals/p2/dismiss': { status: 'dismissed' } })
    renderApp('/assistant')
    const panel = await screen.findByRole('complementary', { name: 'Đề xuất đang chờ' })
    expect(await within(panel).findByText('limits.max_touches: 3 → 2')).toBeInTheDocument()
    expect(within(panel).getByText(/Chỉ tạo bản thử/)).toBeInTheDocument()
    expect(s.posted('/proposals/p1/accept')).toHaveLength(0)
    await userEvent.click(within(panel).getByRole('button', { name: /Thử bản mới/ }))
    await waitFor(() => expect(s.posted('/proposals/p1/accept')).toHaveLength(1))
    await userEvent.click(within(panel).getAllByRole('button', { name: 'Bỏ qua' })[1])
    await waitFor(() => expect(s.posted('/proposals/p2/dismiss')).toHaveLength(1))
  })

  it('is the owner\'s: staff are sent back to the inbox', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/assistant')
    expect(await screen.findByRole('heading', { name: 'Hộp thư' })).toBeInTheDocument()
  })

  it('has an empty state for no proposals', async () => {
    base({ 'GET /proposals': { items: [] } })
    renderApp('/assistant')
    expect(await screen.findByText('Không có đề xuất nào đang chờ.')).toBeInTheDocument()
  })
})
