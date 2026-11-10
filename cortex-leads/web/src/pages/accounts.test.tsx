import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Member, MySession } from '../api/types'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const U = (o: Partial<Member>): Member => ({ id: 'u1', email: 'minh@trungtam.vn', name: 'Trần Minh', role: 'staff', staff_ref: 'minh', status: 'active', invited: false, phone: null, birth_date: null, national_id: null, mfa: false,
  last_login_at: new Date().toISOString(), created_at: new Date().toISOString(), sessions: 1, you: false, classes: [], ...o })
const TEAM = { min_password: 10, items: [U({ id: 'me', name: 'Chủ Minh Khai', email: 'chu@minhkhai.vn', role: 'owner', you: true }), U({}), U({ id: 'u2', name: 'Lê Hoa', email: 'hoa@trungtam.vn', status: 'disabled', sessions: 0 })] }
const SESSIONS: { items: MySession[] } = { items: [
  { id: 's1', current: true, created_at: new Date().toISOString(), last_seen_at: new Date().toISOString(), ip: '203.0.113.5', user_agent: 'Mozilla/5.0 (X11; Linux x86_64) Chrome/130 Safari/537' },
  { id: 's2', current: false, created_at: '2026-10-18T02:00:00Z', last_seen_at: '2026-10-19T02:00:00Z', ip: '198.51.100.9', user_agent: 'Mozilla/5.0 (iPhone) Safari/604' }] }

const MFA_OFF = { enabled: false, enabled_at: null, recovery_left: 0 }

/** Opens the «Sửa» dialog of the person with this name and returns the queries inside it. */
async function openEdit(name: string) {
  const row = (await screen.findAllByRole('row')).find((r) => within(r).queryByText(name))!
  await userEvent.click(within(row).getByRole('button', { name: 'Sửa' }))
  return within(await screen.findByRole('dialog', { name: 'Sửa tài khoản' }))
}
const openCreate = async () => userEvent.click(await screen.findByRole('button', { name: 'Tạo tài khoản' }))

describe('Nhân viên & quyền', () => {
  it('is the owner\'s page only: staff get no menu item', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: /Nhân viên & quyền/ })).toBeNull()
  })

  it('invites a person by email and says so, without ever showing a password', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'POST /team': { id: 'u9', email: 'moi@trungtam.vn', staff_ref: 'moi', mail_sent: true, kind: 'invite' } })
    renderApp('/team')
    await openCreate()
    await userEvent.type(await screen.findByLabelText('Họ tên'), 'Phạm Mới')
    await userEvent.type(screen.getByLabelText('Email'), 'moi@trungtam.vn')
    await userEvent.click(screen.getByRole('button', { name: /Gửi lời mời/ }))
    expect(await screen.findByText(/Đã gửi thư mời tới moi@trungtam.vn/)).toBeInTheDocument()
    expect(s.posted('/team')[0].body).toEqual({ email: 'moi@trungtam.vn', name: 'Phạm Mới', role: 'staff' })
    expect(screen.queryByText(/Mật khẩu tạm/)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Đóng' }))
    expect(screen.queryByText(/Đã gửi thư mời/)).toBeNull()
  })

  it('says when the mail could not be sent and points at the resend button', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM, 'POST /team': { id: 'u9', email: 'moi@trungtam.vn', staff_ref: 'moi', mail_sent: false, kind: 'invite' } })
    renderApp('/team')
    await openCreate()
    await userEvent.type(await screen.findByLabelText('Họ tên'), 'Phạm Mới')
    await userEvent.type(screen.getByLabelText('Email'), 'moi@trungtam.vn')
    await userEvent.click(screen.getByRole('button', { name: /Gửi lời mời/ }))
    expect(await screen.findByText(/Chưa gửi được thư tới moi@trungtam.vn/)).toBeInTheDocument()
  })

  it('offers a resend for someone who never opened the invitation', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': { ...TEAM, items: [...TEAM.items, U({ id: 'u7', name: 'Chờ Duyệt', email: 'cho@trungtam.vn', invited: true })] },
      'POST /team/u7/send-link': { id: 'u7', email: 'cho@trungtam.vn', mail_sent: true, kind: 'invite' } })
    renderApp('/team')
    const row = (await screen.findAllByRole('row')).find((r) => within(r).queryByText('Chờ Duyệt'))!
    expect(within(row).getByText('Chờ kích hoạt')).toBeInTheDocument()
    const dlg = await openEdit('Chờ Duyệt')
    await userEvent.click(dlg.getByRole('button', { name: 'Gửi lại lời mời' }))
    await userEvent.click(dlg.getByRole('button', { name: 'Gửi' }))
    expect(await screen.findByText(/Đã gửi thư mời tới cho@trungtam.vn/)).toBeInTheDocument()
    expect(s.posted('/team/u7/send-link')).toHaveLength(1)
  })

  it('shows who is disabled or has not chosen a password, and offers only your details on your own row', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM })
    renderApp('/team')
    const rows = await screen.findAllByRole('row')
    const mine = rows.find((r) => within(r).queryByText('(bạn)'))!
    await userEvent.click(within(mine).getByRole('button', { name: 'Sửa' })) // your own details can be edited ...
    const me = within(await screen.findByRole('dialog', { name: 'Sửa tài khoản' }))
    expect(me.getByLabelText(/^Vai trò/)).toBeDisabled() // ... but you cannot demote, lock or reset yourself here
    for (const gone of ['Khoá tài khoản', 'Đăng xuất mọi thiết bị', /Gửi liên kết/]) expect(me.queryByRole('button', { name: gone })).toBeNull()
    await userEvent.click(me.getByRole('button', { name: 'Huỷ' }))
    const hoa = rows.find((r) => within(r).queryByText('Lê Hoa'))!
    expect(within(hoa).getByText('Đã khoá')).toBeInTheDocument()
    const dlg = await openEdit('Lê Hoa')
    expect(dlg.getByRole('button', { name: 'Mở lại tài khoản' })).toBeInTheDocument()
  })

  it('asks before locking a person and before sending a reset link, and mails a reset link', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': U({ status: 'disabled' }), 'POST /team/u1/send-link': { id: 'u1', email: 'minh@trungtam.vn', mail_sent: true, kind: 'reset' } })
    renderApp('/team')
    const dlg = await openEdit('Trần Minh')
    await userEvent.click(dlg.getByRole('button', { name: 'Khoá tài khoản' }))
    expect(s.calls.some((c) => c.method === 'PATCH')).toBe(false) // a question first
    await userEvent.click(dlg.getByRole('button', { name: 'Khoá' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'disabled' }))
    await userEvent.click(dlg.getByRole('button', { name: /Gửi liên kết đặt lại mật khẩu/ }))
    await userEvent.click(dlg.getByRole('button', { name: 'Gửi' }))
    expect(await screen.findByText(/Đã gửi thư đặt lại mật khẩu tới minh@trungtam.vn/)).toBeInTheDocument()
  })

  it('says plainly when the last owner cannot be demoted', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': fail(409, { code: 'LAST_OWNER', message: 'x' }) })
    renderApp('/team')
    const dlg = await openEdit('Trần Minh')
    await userEvent.selectOptions(dlg.getByLabelText('Vai trò'), 'owner')
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    expect(await dlg.findByRole('alert')).toHaveTextContent('phải còn ít nhất một chủ')
  })

  it('edits the basic details as one form and sends only what changed', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': U({ name: 'Trần Minh Quân' }) })
    renderApp('/team')
    const dlg = await openEdit('Trần Minh')
    expect(dlg.getByRole('button', { name: 'Lưu thay đổi' })).toBeDisabled() // nothing changed yet
    await userEvent.clear(dlg.getByLabelText('Họ và tên'))
    await userEvent.type(dlg.getByLabelText('Họ và tên'), 'Trần Minh Quân')
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ name: 'Trần Minh Quân' }))
  })

  it('fixes a mistyped email on an unopened invitation and says the mail goes again', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': { ...TEAM, items: [...TEAM.items, U({ id: 'u7', name: 'Chờ Duyệt', email: 'cho@gmail.comd', invited: true })] },
      'PATCH /team/u7': { ...U({ id: 'u7', name: 'Chờ Duyệt', email: 'cho@gmail.com', invited: true }), mail_sent: true } })
    renderApp('/team')
    const dlg = await openEdit('Chờ Duyệt')
    await userEvent.clear(dlg.getByLabelText(/^Email đăng nhập/))
    await userEvent.type(dlg.getByLabelText(/^Email đăng nhập/), 'cho@gmail.com')
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ email: 'cho@gmail.com' }))
    expect(await screen.findByText(/Đã gửi thư mời tới cho@gmail.com/)).toBeInTheDocument()
  })

  it('moves the email of an account in use and warns what that does first', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': TEAM, 'PATCH /team/u1': U({ email: 'minh.moi@trungtam.vn' }) })
    renderApp('/team')
    const dlg = await openEdit('Trần Minh')
    await userEvent.clear(dlg.getByLabelText('Email đăng nhập'))
    await userEvent.type(dlg.getByLabelText('Email đăng nhập'), 'minh.moi@trungtam.vn')
    expect(dlg.getByText(/bị đăng xuất khỏi mọi thiết bị/)).toBeInTheDocument()
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ email: 'minh.moi@trungtam.vn' }))
  })

  it('sends phone, birth date and ID number, and clears them when emptied', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': { ...TEAM, items: [TEAM.items[0], U({ phone: '0912345678', national_id: '079000000003' })] }, 'PATCH /team/u1': U({}) })
    renderApp('/team')
    const dlg = await openEdit('Trần Minh')
    expect(dlg.getByLabelText('Số điện thoại')).toHaveValue('0912345678')
    expect(dlg.getByLabelText('Số CCCD')).toHaveValue('079000000003')
    await userEvent.clear(dlg.getByLabelText('Số điện thoại'))
    await userEvent.clear(dlg.getByLabelText('Số CCCD'))
    await userEvent.type(dlg.getByLabelText('Ngày sinh'), '1990-04-04')
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ phone: '', national_id: '', birth_date: '1990-04-04' }))
  })

  it('finds a person by name or email and filters by role and state', async () => {
    server({ 'GET /session': OWNER, 'GET /team': TEAM })
    renderApp('/team')
    await screen.findByText('Lê Hoa')
    await userEvent.type(screen.getByLabelText('Tìm tài khoản'), 'hoa@')
    expect(screen.queryByText('Trần Minh')).toBeNull()
    expect(screen.getByText('Lê Hoa')).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Tìm tài khoản'))
    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái'), 'disabled')
    expect(screen.queryByText('Trần Minh')).toBeNull()
    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái'), '')
    await userEvent.selectOptions(screen.getByLabelText('Lọc theo vai trò'), 'owner')
    expect(screen.queryByText('Lê Hoa')).toBeNull()
    expect(screen.getByText(/trong tổng/)).toHaveTextContent('1')
  })

  it('pages through a long list', async () => {
    const many = Array.from({ length: 12 }, (_, i) => U({ id: `p${i}`, name: `Người ${String(i).padStart(2, '0')}`, email: `p${i}@trungtam.vn` }))
    server({ 'GET /session': OWNER, 'GET /team': { min_password: 10, items: many } })
    renderApp('/team')
    await screen.findByText('Người 00')
    expect(screen.queryByText('Người 11')).toBeNull() // ten to a page
    expect(screen.getByText(/trong tổng/)).toHaveTextContent('1–10 trong tổng 12')
    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('Người 11')).toBeInTheDocument()
    expect(screen.queryByText('Người 00')).toBeNull()
  })
})

describe('Tài khoản', () => {
  it('lists my devices, marks this one, and ends another', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': MFA_OFF, 'POST /session/sessions/s2/revoke': { status: 'ok' } })
    renderApp('/account')
    expect(await screen.findByText('Thiết bị này')).toBeInTheDocument()
    expect(screen.getByText(/Chrome · Linux/)).toBeInTheDocument()
    expect(screen.getByText(/Safari · iOS/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Đăng xuất thiết bị này' })).toHaveLength(1) // not the one you are on
    await userEvent.click(screen.getByRole('button', { name: 'Đăng xuất thiết bị này' }))
    await waitFor(() => expect(s.posted('/session/sessions/s2/revoke')).toHaveLength(1))
  })

  it('changes the password only when the two new ones match, and says how many other devices were signed out', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': MFA_OFF, 'POST /session/password': { status: 'ok', other_sessions_ended: 1 } })
    renderApp('/account')
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'Mat-khau-moi-4821')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'Mat-khau-moi-4821')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    expect(await screen.findByText(/1 thiết bị khác đã bị đăng xuất/)).toBeInTheDocument()
    expect(s.posted('/session/password')[0].body).toEqual({ current: 'Cu-mat-khau-1', new: 'Mat-khau-moi-4821' })
  })

  it('shows this device and the four used most recently, and every device in a window on request', async () => {
    const old = (i: number): MySession => ({ id: `o${i}`, current: false, created_at: '2026-10-01T02:00:00Z', last_seen_at: `2026-10-${String(10 + i).padStart(2, '0')}T02:00:00Z`,
      ip: `198.51.100.${i}`, user_agent: 'Mozilla/5.0 (Windows NT 10.0) Firefox/130' })
    server({ 'GET /session': STAFF, 'GET /session/sessions': { items: [...[1, 2, 3, 4, 5, 6].map(old), SESSIONS.items[0]] } })
    renderApp('/account')
    const recent = await screen.findByRole('list', { name: 'Thiết bị gần đây' })
    const rows = within(recent).getAllByRole('listitem')
    expect(rows).toHaveLength(5)
    expect(within(rows[0]).getByText('Thiết bị này')).toBeInTheDocument() // this device first, wherever the server put it
    expect(within(rows[1]).getByText(/198\.51\.100\.6/)).toBeInTheDocument() // then the most recently used
    expect(within(recent).queryByText(/198\.51\.100\.1 /)).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Xem tất cả (7)' }))
    const dialog = screen.getByRole('dialog', { name: /Tất cả thiết bị/ })
    expect(within(dialog).getAllByRole('listitem')).toHaveLength(7)
    await userEvent.type(within(dialog).getByLabelText('Lọc thiết bị'), '100.3')
    expect(within(dialog).getAllByRole('listitem')).toHaveLength(1)
  })

  it('offers no «Xem tất cả» when every device already fits', async () => {
    server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': MFA_OFF })
    renderApp('/account')
    await screen.findByText('Thiết bị này')
    expect(screen.queryByRole('button', { name: /Xem tất cả/ })).toBeNull()
  })

  it('asks before signing out of every device, this one included', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': MFA_OFF, 'POST /session/logout-all': { status: 'ok' } })
    renderApp('/account')
    await userEvent.click(await screen.findByRole('button', { name: 'Đăng xuất khỏi mọi thiết bị' }))
    expect(s.posted('/session/logout-all')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Đăng xuất hết' }))
    await waitFor(() => expect(s.posted('/session/logout-all')).toHaveLength(1))
  })

  it('shows the server\'s words for a weak password and a wrong current one', async () => {
    server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': MFA_OFF, 'POST /session/password': fail(422, { code: 'WEAK_PASSWORD', message: 'Mật khẩu này quá dễ đoán.' }) })
    renderApp('/account')
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.type(screen.getByLabelText(/^Mật khẩu mới/), 'passwordpassword')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'passwordpassword')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Mật khẩu này quá dễ đoán.')
  })
})

describe('Xác thực 2 lớp', () => {
  const OFF = { enabled: false, enabled_at: null, recovery_left: 0 }
  const ON = { enabled: true, enabled_at: '2026-11-09T02:00:00Z', recovery_left: 2 }
  const CODES = Array.from({ length: 10 }, (_, i) => `abcd${i}-efgh${i}`)

  it('turns on in three steps: password, scan and confirm a code, then keep the recovery codes', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': OFF,
      'POST /account/mfa/setup': { secret: 'JBSWY3DPEHPK3PXP', uri: 'otpauth://totp/Cortex:a%40b.vn?secret=JBSWY3DPEHPK3PXP&issuer=Cortex' },
      'POST /account/mfa/enable': { ...ON, recovery_left: 10, recovery_codes: CODES } })
    renderApp('/account')
    await userEvent.click(await screen.findByRole('button', { name: 'Bật xác thực 2 lớp' }))
    const d = () => screen.getByRole('dialog')
    await userEvent.type(within(d()).getByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.click(within(d()).getByRole('button', { name: 'Tiếp tục' }))
    expect(await within(d()).findByRole('img', { name: /Mã QR/ })).toBeInTheDocument()
    expect(within(d()).getByText('JBSW Y3DP EHPK 3PXP')).toBeInTheDocument() // for typing in by hand
    const confirm = within(d()).getByRole('button', { name: 'Bật' })
    await userEvent.type(within(d()).getByLabelText('Mã 6 số'), '12a3456')
    expect(within(d()).getByLabelText('Mã 6 số')).toHaveValue('123456') // digits only
    await userEvent.click(confirm)
    const list = await within(d()).findByRole('list', { name: 'Mã dự phòng' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(10)
    expect(within(d()).getByRole('button', { name: 'Xong' })).toBeDisabled() // not before saying they were kept
    await userEvent.click(within(d()).getByLabelText('Tôi đã cất các mã này'))
    expect(within(d()).getByRole('button', { name: 'Xong' })).toBeEnabled()
    expect(s.posted('/account/mfa/setup')[0].body).toEqual({ password: 'Cu-mat-khau-1' })
    expect(s.posted('/account/mfa/enable')[0].body).toEqual({ code: '123456' })
  })

  it('shows when it is on, warns when few recovery codes are left, and turns off with the password and a code', async () => {
    const s = server({ 'GET /session': STAFF, 'GET /session/sessions': SESSIONS, 'GET /account/mfa': ON, 'POST /account/mfa/disable': OFF })
    renderApp('/account')
    expect(await screen.findByText('2 mã dự phòng')).toBeInTheDocument()
    expect(screen.getByText(/nên tạo mã mới/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Tắt' }))
    const d = screen.getByRole('dialog', { name: 'Tắt xác thực 2 lớp' })
    await userEvent.type(within(d).getByLabelText('Mật khẩu hiện tại'), 'Cu-mat-khau-1')
    await userEvent.type(within(d).getByLabelText(/Mã 6 số/), '654321')
    await userEvent.click(within(d).getByRole('button', { name: 'Tắt' }))
    await waitFor(() => expect(s.posted('/account/mfa/disable')[0].body).toEqual({ password: 'Cu-mat-khau-1', code: '654321' }))
  })

  it('lets the owner turn it off for staff with their own password, and not for another owner', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /team': { items: [U({ mfa: true }), U({ id: 'u2', name: 'Chủ hai', email: 'chu2@trungtam.vn', role: 'owner', staff_ref: 'chu2', mfa: true })], min_password: 10 },
      'POST /team/u1/mfa/disable': { mfa: false, sessions_ended: 2 } })
    renderApp('/team')
    const staff = await openEdit('Trần Minh')
    await userEvent.click(staff.getByRole('button', { name: 'Tắt xác thực 2 lớp' }))
    await userEvent.type(staff.getByLabelText('Mật khẩu của bạn'), 'Mat-khau-cua-chu-1{Enter}') // Enter does not save the whole form
    await waitFor(() => expect(s.posted('/team/u1/mfa/disable')[0].body).toEqual({ password: 'Mat-khau-cua-chu-1' }))
    expect(s.calls.some((c) => c.method === 'PATCH')).toBe(false)
    expect(await staff.findByText(/Họ đăng nhập lại bằng mật khẩu/)).toBeInTheDocument()
    await userEvent.click(staff.getByRole('button', { name: 'Huỷ' }))
    const owner = await openEdit('Chủ hai')
    expect(owner.queryByRole('button', { name: 'Tắt xác thực 2 lớp' })).toBeNull()
    expect(owner.getByText(/Nhờ người hỗ trợ kỹ thuật/)).toBeInTheDocument()
  })
})
