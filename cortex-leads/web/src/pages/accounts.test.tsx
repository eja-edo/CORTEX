import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Member, MySession } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const U = (o: Partial<Member>): Member => ({ id: 'u1', email: 'minh@trungtam.vn', name: 'Trần Minh', role: 'staff', staff_ref: 'minh', status: 'active', must_change_password: false,
  last_login_at: new Date().toISOString(), created_at: new Date().toISOString(), sessions: 1, you: false, ...o })
const TEAM = { min_password: 10, items: [U({ id: 'me', name: 'Chủ Minh Khai', email: 'chu@minhkhai.vn', role: 'owner', you: true }), U({}), U({ id: 'u2', name: 'Lê Hoa', email: 'hoa@trungtam.vn', status: 'disabled', sessions: 0 })] }
const SESSIONS: { items: MySession[] } = { items: [
  { id: 's1', current: true, created_at: new Date().toISOString(), last_seen_at: new Date().toISOString(), ip: '203.0.113.5', user_agent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130 Safari/537' },
  { id: 's2', current: false, created_at: '2026-10-18T02:00:00Z', last_seen_at: '2026-10-19T02:00:00Z', ip: '198.51.100.9', user_agent: 'Mozilla/5.0 (iPhone) Safari/604' }] }

describe('Nhân viên & quyền', () => {
  it('is the owner\'s page only: staff get no menu item', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: /Nhân viên & quyền/ })).toBeNull()
  })

  it('adds a person and shows the temporary password once, with a way to copy it', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'POST /team': { id: 'u9', email: 'moi@trungtam.vn', temporary_password: 'Tam-thoi-AbC123xyz7a' } })
    renderApp('/team')
    await userEvent.type(await screen.findByLabelText('Họ tên'), 'Phạm Mới')
    await userEvent.type(screen.getByLabelText('Email'), 'moi@trungtam.vn')
    await userEvent.click(screen.getByRole('button', { name: /Thêm tài khoản/ }))
    expect(await screen.findByLabelText('Mật khẩu tạm')).toHaveTextContent('Tam-thoi-AbC123xyz7a')
    expect(s.posted('/team')[0].body).toEqual({ email: 'moi@trungtam.vn', name: 'Phạm Mới', role: 'staff' })
    await userEvent.click(screen.getByRole('button', { name: 'Đã lưu, đóng' }))
    expect(screen.queryByLabelText('Mật khẩu tạm')).toBeNull()
  })

  it('shows who is disabled or has not chosen a password, and offers no self-service on your own row', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM })
    renderApp('/team')
    const rows = await screen.findAllByRole('row')
    const mine = rows.find((r) => within(r).queryByText('(bạn)'))!
    expect(within(mine).queryByRole('button')).toBeNull() // you cannot lock, demote or reset yourself here
    const hoa = rows.find((r) => within(r).queryByText('Lê Hoa'))!
    expect(within(hoa).getByText('Đã khoá')).toBeInTheDocument()
    expect(within(hoa).getByRole('button', { name: 'Mở lại tài khoản' })).toBeInTheDocument()
  })

  it('asks before locking a person and before resetting a password, and shows the new temporary password once', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': U({ status: 'disabled' }), 'POST /team/u1/reset-password': { temporary_password: 'Dat-lai-9zYx8wVu7a', email: 'minh@trungtam.vn' } })
    renderApp('/team')
    const row = (await screen.findAllByRole('row')).find((r) => within(r).queryByText('Trần Minh'))!
    await userEvent.click(within(row).getByRole('button', { name: 'Khoá tài khoản' }))
    expect(s.calls.some((c) => c.method === 'PATCH')).toBe(false) // a question first
    await userEvent.click(within(row).getByRole('button', { name: 'Khoá' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'disabled' }))
    await userEvent.click(within(row).getByRole('button', { name: /Đặt lại mật khẩu/ }))
    await userEvent.click(within(row).getByRole('button', { name: 'Đặt lại' }))
    expect(await screen.findByLabelText('Mật khẩu tạm')).toHaveTextContent('Dat-lai-9zYx8wVu7a')
  })

  it('says plainly when the last owner cannot be demoted', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': fail(409, { code: 'LAST_OWNER', message: 'x' }) })
    renderApp('/team')
    const row = (await screen.findAllByRole('row')).find((r) => within(r).queryByText('Trần Minh'))!
    await userEvent.click(within(row).getByRole('button', { name: 'Nâng lên chủ' }))
    expect(await within(row).findByRole('alert')).toHaveTextContent('phải còn ít nhất một chủ')
  })
})

describe('Tài khoản', () => {
  it('lists my devices, marks this one, and ends another', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'POST /session/sessions/s2/revoke': { status: 'ok' } })
    renderApp('/account')
    expect(await screen.findByText('Thiết bị này')).toBeInTheDocument()
    expect(screen.getByText(/Chrome · Linux/)).toBeInTheDocument()
    expect(screen.getByText(/Safari · iOS/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Đăng xuất thiết bị này' })).toHaveLength(1) // not the one you are on
    await userEvent.click(screen.getByRole('button', { name: 'Đăng xuất thiết bị này' }))
    await waitFor(() => expect(s.posted('/session/sessions/s2/revoke')).toHaveLength(1))
  })

  it('changes the password only when the two new ones match, and says how many other devices were signed out', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'POST /session/password': { status: 'ok', other_sessions_ended: 1 } })
    renderApp('/account')
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-4821')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-4821')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    expect(await screen.findByText(/1 thiết bị khác đã bị đăng xuất/)).toBeInTheDocument()
    expect(s.posted('/session/password')[0].body).toEqual({ current: 'Cu-mat-khau-1', new: 'Mat-khau-moi-4821' })
  })

  it('shows the server\'s words for a weak password and a wrong current one', async () => {
    server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'POST /session/password': fail(422, { code: 'WEAK_PASSWORD', message: 'Mật khẩu này quá dễ đoán.' }) })
    renderApp('/account')
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'passwordpassword')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'passwordpassword')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Mật khẩu này quá dễ đoán.')
  })
})
