import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import { SidePanel } from '../components/ui'
import { CONV, LIST } from '../test/fixtures'
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

  it('asks for the code after the right password when two-step sign-in is on, and signs in only then', async () => {
    const s = server({ 'GET /session': fail(401, 'x'), 'POST /session/login': { mfa_required: true },
      'POST /session/mfa': fail(401, { code: 'BAD_MFA_CODE', message: 'Mã không đúng hoặc đã được dùng.' }) })
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'an@trungtam.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'dung-mat-khau-1')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
    const code = await screen.findByLabelText('Mã xác thực')
    expect(screen.queryByLabelText('Mật khẩu')).toBeNull()
    await userEvent.type(code, '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Mã không đúng hoặc đã được dùng.')
    expect(s.posted('/session/mfa')[0].body).toEqual({ code: '123456' })
    await userEvent.click(screen.getByRole('button', { name: /Dùng mã dự phòng/ }))
    expect(screen.getByLabelText('Mã dự phòng')).toBeInTheDocument()
  })

  it('sends the person back to the password when the time for the code ran out', async () => {
    server({ 'GET /session': fail(401, 'x'), 'POST /session/login': { mfa_required: true },
      'POST /session/mfa': fail(401, { code: 'MFA_EXPIRED', message: 'Đã quá thời gian nhập mã. Hãy đăng nhập lại từ đầu.' }) })
    renderApp('/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'an@trungtam.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'dung-mat-khau-1')
    await userEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))
    await userEvent.type(await screen.findByLabelText('Mã xác thực'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Đăng nhập lại' }))
    expect(screen.getByLabelText('Mật khẩu')).toBeInTheDocument()
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

  it('shows the owner the whole menu and the count of customers who need a person', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    const nav = await screen.findByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).getByRole('link', { name: /Hộp thư/ })).toHaveTextContent('3')
    for (const l of ['Kỹ năng', 'AI tổng']) expect(within(nav).getByRole('link', { name: l })).toBeInTheDocument()
    expect(within(nav).getByRole('link', { name: 'Dữ liệu' })).toHaveAttribute('href', '/data')
    for (const soon of ['Báo cáo', 'Việc hôm nay']) expect(within(nav).queryByText(soon)).toBeNull() // a page that does not exist is not in the menu
    expect(screen.queryByText('AI đang chạy')).toBeNull() // the kill switch lives in Cài đặt → AI now
  })

  it('gives staff no AI tổng', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: 'AI tổng' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Dừng khẩn cấp' })).toBeNull()
    expect(screen.getByText(/Đăng xuất · nv1/)).toBeInTheDocument()
  })

  it('no longer carries a kill-switch card in the sidebar', async () => {
    server({ 'GET /session': { ...OWNER, ai: 'paused' }, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('button', { name: 'Dừng khẩn cấp' })).toBeNull()
    expect(screen.queryByText('AI đang tạm dừng')).toBeNull()
  })

  it('shows a clear error when the server cannot be reached', async () => {
    server({ 'GET /session': fail(500, 'boom') })
    renderApp('/inbox')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không kết nối được máy chủ')
  })

  it('has one "Lớp học" entry where lessons, grading and assignments used to be three, and the old addresses still lead there', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [] }, 'GET /lessons': { items: [], limit: 100, can_upload: false, max_mb: 1, classes: [] } })
    renderApp('/lessons')  // an old bookmark
    const nav = await screen.findByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).getByRole('link', { name: 'Lớp học' })).toHaveAttribute('href', '/classes')
    for (const gone of ['Bài giảng', 'Chấm bài', 'Bài tập']) expect(within(nav).queryByRole('link', { name: gone })).toBeNull()
    expect(await screen.findByRole('heading', { name: 'Lớp học' })).toBeInTheDocument()
  })

  it('gives customer care no Lớp học entry: the classes are the owner\'s and the teachers\'', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    const nav = await screen.findByRole('navigation', { name: 'Điều hướng chính' })
    expect(within(nav).queryByRole('link', { name: 'Lớp học' })).toBeNull()
    expect(within(nav).getByRole('link', { name: /Hộp thư/ })).toBeInTheDocument()
  })
})

describe('the menu', () => {
  const nav = () => screen.findByRole('navigation', { name: 'Điều hướng chính' })
  afterEach(() => localStorage.clear())

  it('puts the entries under their sections, and groups the AI pages', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    const n = await nav()
    expect(within(n).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Công việc', 'Nghiệp vụ', 'Quản trị'])
    expect(within(n).getByRole('button', { name: 'Vận hành AI' })).toHaveAttribute('aria-expanded', 'true')
  })

  it('folds a group, remembers it, and opens it again when the person lands on a page inside', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST, 'GET /skills': { items: [], counts: {}, min_trial_runs: 10 } })
    const first = renderApp('/inbox')
    await userEvent.click(within(await nav()).getByRole('button', { name: 'Vận hành AI' }))
    expect(screen.queryByRole('link', { name: 'Kỹ năng' })).toBeNull()
    first.unmount()
    const second = renderApp('/inbox')
    expect(within(await nav()).getByRole('button', { name: 'Vận hành AI' })).toHaveAttribute('aria-expanded', 'false')
    second.unmount()
    renderApp('/skills')
    expect(within(await nav()).getByRole('link', { name: 'Kỹ năng' })).toBeInTheDocument()
  })

  it('drops a group and a section with nothing the person may open', async () => {
    server({ 'GET /session': { ...STAFF, permissions: ['account.self', 'lessons.read'] }, 'GET /classes': { items: [] } })
    renderApp('/classes')
    const n = await nav()
    expect(within(n).getAllByRole('heading').map((h) => h.textContent)).toEqual(['Nghiệp vụ', 'Quản trị'])
    expect(within(n).queryByRole('button', { name: 'Đào tạo' })).toBeNull() // only Lớp học left: a group of one is just that entry
    expect(within(n).queryByRole('button', { name: 'Vận hành AI' })).toBeNull()
    expect(within(n).getByRole('link', { name: 'Lớp học' })).toBeInTheDocument()
  })
})

describe('on a narrow screen', () => {
  const phone = (width: number) => {
    window.matchMedia = ((q: string) => ({ matches: Number(/max-width: ([\d.]+)px/.exec(q)?.[1] ?? 0) >= width, addEventListener() {}, removeEventListener() {} })) as unknown as typeof window.matchMedia
  }
  afterEach(() => { Reflect.deleteProperty(window, 'matchMedia') })

  it('opens the menu as a drawer, shuts the page behind it, and closes it on Escape with focus back on the button', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST })
    renderApp('/inbox')
    const open = await screen.findByRole('button', { name: 'Mở menu' })
    expect(open).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(open)
    expect(open.closest('[inert]')).not.toBeNull()
    expect(screen.getByRole('button', { name: 'Đóng menu' })).toHaveFocus()
    await userEvent.keyboard('{Escape}')
    expect(open.closest('[inert]')).toBeNull()
    expect(open).toHaveFocus()
  })

  it('closes the drawer when a menu entry takes the person to another page', async () => {
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': EMPTY_LIST, 'GET /audit?page=1&page_size=20': { items: [], total: 0, page: 1, pages: 1, page_size: 20, actors: [], categories: {} } })
    renderApp('/inbox')
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Điều hướng chính' })).getByRole('link', { name: 'Nhật ký hoạt động' }))
    expect(await screen.findByRole('button', { name: 'Mở menu' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('leaves a phone on the list of conversations instead of opening the first one', async () => {
    phone(390)
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': LIST, [`GET /conversations/${CONV.id}`]: CONV })
    renderApp('/inbox')
    expect(await screen.findByRole('button', { name: new RegExp(LIST.items[0].name) })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Hội thoại' })).not.toBeInTheDocument()
  })

  it('still opens the first conversation where the list and the conversation fit side by side', async () => {
    phone(1100)
    server({ 'GET /session': OWNER, 'GET /conversations?filter=need_human': LIST, [`GET /conversations/${CONV.id}`]: CONV })
    renderApp('/inbox')
    expect(await screen.findByRole('region', { name: 'Hội thoại' })).toBeInTheDocument()
  })

  it('closes a side panel with its own button and with Escape, and only there', async () => {
    phone(390)
    const closed: string[] = []
    const { rerender } = render(<SidePanel label="Chi tiết" open onClose={() => closed.push('x')}>nội dung</SidePanel>)
    await userEvent.click(screen.getByRole('button', { name: 'Đóng' }))
    await userEvent.keyboard('{Escape}')
    expect(closed).toHaveLength(2)
    phone(1400)
    rerender(<SidePanel label="Chi tiết" open={false} onClose={() => closed.push('x')}>nội dung</SidePanel>)
    rerender(<SidePanel label="Chi tiết" open onClose={() => closed.push('x')}>nội dung</SidePanel>)
    await userEvent.keyboard('{Escape}')
    expect(closed).toHaveLength(2)  // on a wide screen the panel is part of the page: Escape must not clear what was picked
  })
})
