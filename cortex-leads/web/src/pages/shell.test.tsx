import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const EMPTY_LIST = { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } }

describe('sign-in and shell', () => {
  it('sends a signed-out visitor to the login page and gives one answer for a wrong email or password', async () => {
    const s = server({ 'GET /session': fail(401, 'not signed in'), 'POST /session/login': fail(401, { code: 'BAD_CREDENTIALS', message: 'x' }) })
    renderApp('/inbox')
    await userEvent.type(await screen.findByLabelText('Email'), 'an@trungtam.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'mat-khau-sai-1')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Email hoặc mật khẩu không đúng.')
    expect(s.posted('/session/login')[0].body).toEqual({ email: 'an@trungtam.vn', password: 'mat-khau-sai-1' })
  })

  it('says how long to wait when the account is locked, without saying why it is locked', async () => {
    server({ 'GET /session': fail(401, 'x'), 'POST /session/login': fail(429, { code: 'LOGIN_LOCKED', retry_after_s: 840 }) })
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'an@trungtam.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'dung-mat-khau-1')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Hãy đợi 14 phút rồi thử lại')
  })

  it('does not let an empty email or password be submitted', async () => {
    server({ 'GET /session': fail(401, 'x') })
    renderApp('/login')
    const go = await screen.findByRole('button', { name: 'Đăng nhập' })
    expect(go).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Email'), 'an@trungtam.vn')
    expect(go).toBeDisabled()
  })

  it('shows nothing but the new-password screen to someone still holding a temporary password', async () => {
    const s = server({ 'GET /session': { ...STAFF, must_change_password: true }, 'POST /session/password': { status: 'ok', other_sessions_ended: 0 } })
    renderApp('/inbox')
    expect(await screen.findByRole('heading', { name: 'Đặt mật khẩu mới' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation')).toBeNull()
    const go = screen.getByRole('button', { name: 'Đổi mật khẩu' })
    await userEvent.type(screen.getByLabelText('Mật khẩu tạm bạn được cấp'), 'Tam-thoi-12345')
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-4821')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-0000')
    expect(screen.getByText('Hai mật khẩu chưa giống nhau.')).toBeInTheDocument()
    expect(go).toBeDisabled()
    await userEvent.clear(screen.getByLabelText('Nhập lại mật khẩu mới'))
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-4821')
    await userEvent.click(go)
    await waitFor(() => expect(s.posted('/session/password')).toHaveLength(1))
    expect(s.posted('/session/password')[0].body).toEqual({ current: 'Tam-thoi-12345', new: 'Mat-khau-moi-4821' })
  })

  it('shows the owner the whole menu and the count of customers who need a person', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    const nav = await screen.findByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).getByRole('link', { name: /Hộp thư/ })).toHaveTextContent('3')
    for (const l of ['Kỹ năng', 'Sandbox', 'AI tổng']) expect(within(nav).getByRole('link', { name: l })).toBeInTheDocument()
    expect(within(nav).getByText('Dữ liệu')).toHaveAttribute('aria-disabled', 'true') // not built yet: honest, not a dead link
    expect(screen.getByText('AI đang chạy')).toBeInTheDocument()
    expect(screen.getByText('Chế độ nháp · nhân viên duyệt')).toBeInTheDocument()
  })

  it('gives staff no kill switch and no AI tổng', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: 'AI tổng' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Dừng khẩn cấp' })).toBeNull()
    expect(screen.getByText(/Đăng xuất · nv1/)).toBeInTheDocument()
  })

  it('stops the AI only after a deliberate second step, with the CSRF token', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST, 'POST /kill-switch': { changed: 1 } })
    renderApp('/inbox')
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng khẩn cấp' }))
    expect(s.posted('/kill-switch')).toHaveLength(0) // one click is only a question
    const group = screen.getByRole('group', { name: 'Xác nhận dừng khẩn cấp' })
    await userEvent.click(within(group).getByRole('button', { name: 'Huỷ' }))
    expect(s.posted('/kill-switch')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Dừng khẩn cấp' }))
    await userEvent.click(screen.getByRole('button', { name: 'Dừng ngay' }))
    await waitFor(() => expect(s.posted('/kill-switch')).toHaveLength(1))
    expect(s.posted('/kill-switch')[0]).toMatchObject({ body: { paused: true }, csrf: 'csrf-token-1' })
  })

  it('shows a paused AI in red with the way back, and the reassurance that staff carry on', async () => {
    server({ 'GET /session': { ...OWNER, ai: 'paused' }, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    expect(await screen.findByText('AI đang tạm dừng')).toBeInTheDocument()
    expect(screen.getByText('Nhân viên vẫn trả lời bình thường.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bật lại AI' })).toBeInTheDocument()
  })

  it('says so when there is no care sandbox yet', async () => {
    server({ 'GET /session': { ...OWNER, ai: 'none' }, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    expect(await screen.findByText('Chưa có sandbox chăm sóc khách.')).toBeInTheDocument()
  })

  it('shows a clear error when the server cannot be reached', async () => {
    server({ 'GET /session': fail(500, 'boom') })
    renderApp('/inbox')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không kết nối được máy chủ')
  })

  it('has one "Lớp học" entry where lessons, grading and assignments used to be three, and the old addresses still lead there', async () => {
    server({ 'GET /session': STAFF, 'GET /classes': { items: [] }, 'GET /lessons': { items: [], limit: 100, can_upload: false, max_mb: 1, classes: [] } })
    renderApp('/lessons')  // an old bookmark
    const nav = await screen.findByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).getByRole('link', { name: 'Lớp học' })).toHaveAttribute('href', '/classes')
    for (const gone of ['Bài giảng', 'Chấm bài', 'Bài tập']) expect(within(nav).queryByRole('link', { name: gone })).toBeNull()
    expect(await screen.findByRole('heading', { name: 'Lớp học' })).toBeInTheDocument()
  })
})
