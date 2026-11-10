import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { fail, renderApp, server } from '../test/harness'
import type { AdminMe, TenantDetail, TenantRow } from './api'

const ME: AdminMe = { email: 'ops@cortex.vn', name: 'Vận hành', csrf: 'admin-csrf', expires_at: new Date(Date.now() + 1_800_000).toISOString() }
const ROW: TenantRow = { id: 't1', name: 'Trung tâm Minh Khai', timezone: 'Asia/Ho_Chi_Minh', created_at: '2026-10-01T02:00:00Z', ai: 'running', sandboxes: 4, sandboxes_paused: 0,
  accounts: 3, owners: 1, owners_waiting: 0, conversations_7d: 42, last_login_at: new Date().toISOString() }
const DETAIL: TenantDetail = { ...ROW, sandboxes_missing: [],
  sandbox_list: [{ id: 'sb1', purpose: 'customer_care', label: 'Chăm sóc khách', title: null, status: 'active', send_mode: 'manual' }],
  account_list: [{ id: 'u1', email: 'chu@minhkhai.vn', name: 'Chủ Minh Khai', role: 'owner', status: 'active', invited: false, mfa: true, sessions: 2, last_login_at: null, created_at: '2026-10-01T02:00:00Z' }] }
const SIGNED_OUT = fail(401, { code: 'ADMIN_SIGNED_OUT' })

describe('Trang quản trị nền tảng', () => {
  it('asks for the password, then the code, and only then shows the businesses', async () => {
    let signedIn = false
    const s = server({
      'GET /api/admin/session': () => (signedIn ? ME : SIGNED_OUT),
      'POST /api/admin/session/login': { mfa_required: true },
      'POST /api/admin/session/mfa': () => { signedIn = true; return ME },
      'GET /api/admin/tenants': { items: [ROW] },
    })
    renderApp('/admin')
    await userEvent.type(await screen.findByLabelText('Email'), 'ops@cortex.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'Admin-pass-98765')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    await userEvent.type(await screen.findByLabelText('Mã xác thực'), '123456')
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận' }))
    expect(await screen.findByRole('link', { name: 'Trung tâm Minh Khai' })).toBeInTheDocument()
    expect(screen.getByText('AI đang chạy')).toBeInTheDocument()
    expect(s.calls.every((c) => c.path.startsWith('/api/admin'))).toBe(true)  // nothing of the console's API is touched
  })

  it('says the same thing for a wrong password as for an unknown account', async () => {
    server({ 'GET /api/admin/session': SIGNED_OUT, 'POST /api/admin/session/login': fail(401, { code: 'BAD_CREDENTIALS' }) })
    renderApp('/admin/login')
    await userEvent.type(await screen.findByLabelText('Email'), 'x@y.vn')
    await userEvent.type(screen.getByLabelText('Mật khẩu'), 'sai')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp tục' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Email hoặc mật khẩu không đúng.')
  })

  it('creates a business and invites its owner by mail, never showing a password', async () => {
    const s = server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants': { items: [] }, 'POST /api/admin/tenants': { id: 't9', owner: { email: 'chu@moi.vn', mail_sent: true } } })
    renderApp('/admin')
    await userEvent.click(await screen.findByRole('button', { name: /Tạo doanh nghiệp/ }))
    const dlg = within(await screen.findByRole('dialog', { name: 'Tạo doanh nghiệp' }))
    await userEvent.type(dlg.getByLabelText('Tên doanh nghiệp'), 'Trung tâm Mới')
    await userEvent.type(dlg.getByLabelText('Họ tên chủ'), 'Chủ Mới')
    await userEvent.type(dlg.getByLabelText('Email chủ'), 'chu@moi.vn')
    await userEvent.click(dlg.getByRole('button', { name: 'Tạo và gửi thư mời' }))
    expect(await dlg.findByText(/gửi thư mời tới chu@moi.vn/)).toBeInTheDocument()
    expect(s.posted('/api/admin/tenants')[0].body).toEqual({ name: 'Trung tâm Mới', timezone: 'Asia/Ho_Chi_Minh', owner_email: 'chu@moi.vn', owner_name: 'Chủ Mới' })
    expect(s.posted('/api/admin/tenants')[0].csrf).toBe('admin-csrf')
    expect(screen.queryByText(/Mật khẩu tạm/)).toBeNull()
  })

  it('stops every business only with the admin\'s code', async () => {
    const s = server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants': { items: [ROW] }, 'POST /api/admin/ai': { tenants: 1, sandboxes_changed: 4 } })
    renderApp('/admin')
    await userEvent.click(await screen.findByRole('button', { name: /Dừng tất cả/ }))
    const dlg = within(await screen.findByRole('dialog'))
    const go = dlg.getByRole('button', { name: 'Tạm dừng tất cả' })
    expect(go).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/Mã 6 số/), '654321')
    await userEvent.click(go)
    expect(await dlg.findByText(/4 sandbox đổi trạng thái/)).toBeInTheDocument()
    expect(s.posted('/api/admin/ai')[0].body).toEqual({ paused: true, code: '654321' })
  })

  it('rescues an owner who lost their phone: the admin\'s code turns their second step off', async () => {
    const s = server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants/t1': DETAIL, 'POST /api/admin/tenants/t1/users/u1/mfa/reset': { sessions_ended: 2 } })
    renderApp('/admin/tenants/t1')
    await userEvent.click(await screen.findByRole('button', { name: 'Thao tác với chu@minhkhai.vn' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Tắt xác thực 2 lớp/ }))
    const dlg = within(await screen.findByRole('dialog', { name: 'Tắt xác thực 2 lớp' }))
    await userEvent.type(dlg.getByLabelText(/Mã 6 số/), '111222')
    await userEvent.click(dlg.getByRole('button', { name: 'Tắt xác thực 2 lớp' }))
    expect(await dlg.findByText(/2 thiết bị bị đăng xuất/)).toBeInTheDocument()
    expect(s.posted('/api/admin/tenants/t1/users/u1/mfa/reset')[0].body).toEqual({ code: '111222' })
  })

  it('sends a reset link rather than setting a password, and warns when a business has no owner', async () => {
    const noOwner = { ...DETAIL, owners: 0, account_list: [{ ...DETAIL.account_list[0], role: 'staff' as const, mfa: false, sessions: 0 }] }
    server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants/t1': noOwner, 'POST /api/admin/tenants/t1/users/u1/send-link': { email: 'chu@minhkhai.vn', mail_sent: true, kind: 'reset' } })
    renderApp('/admin/tenants/t1')
    expect(await screen.findByText(/không còn chủ nào đang hoạt động/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Thao tác với chu@minhkhai.vn' }))
    expect(screen.queryByRole('menuitem', { name: /Tắt xác thực 2 lớp/ })).toBeNull()
    await userEvent.click(await screen.findByRole('menuitem', { name: /đặt lại mật khẩu/ }))
    expect(await screen.findByText(/Đã gửi liên kết đặt lại mật khẩu tới chu@minhkhai.vn/)).toBeInTheDocument()
  })

  it('fixes a typo in an invited owner\'s email without a code, but asks for one to move an account in use', async () => {
    const invited = { ...DETAIL, account_list: [{ ...DETAIL.account_list[0], email: 'chu@minhkhai.vncom', invited: true, mfa: false, sessions: 0 }] }
    const s = server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants/t1': invited,
      'PATCH /api/admin/tenants/t1/users/u1': { email: 'chu@minhkhai.vn', name: 'Chủ Minh Khai', email_moved: true, sessions_ended: 0, mail_sent: true } })
    renderApp('/admin/tenants/t1')
    await userEvent.click(await screen.findByRole('button', { name: 'Thao tác với chu@minhkhai.vncom' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Sửa tên hoặc email/ }))
    const dlg = within(await screen.findByRole('dialog', { name: 'Sửa tài khoản' }))
    const field = dlg.getByLabelText('Email đăng nhập')
    await userEvent.clear(field)
    await userEvent.type(field, 'chu@minhkhai.vn')
    expect(dlg.queryByLabelText(/Mã 6 số/)).toBeNull()
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu' }))
    expect(await dlg.findByText(/gửi lại thư mời tới chu@minhkhai.vn/)).toBeInTheDocument()
    expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ email: 'chu@minhkhai.vn' })
  })

  it('asks for the admin\'s code before moving the email of an account in use', async () => {
    server({ 'GET /api/admin/session': ME, 'GET /api/admin/tenants/t1': DETAIL })
    renderApp('/admin/tenants/t1')
    await userEvent.click(await screen.findByRole('button', { name: 'Thao tác với chu@minhkhai.vn' }))
    await userEvent.click(await screen.findByRole('menuitem', { name: /Sửa tên hoặc email/ }))
    const dlg = within(await screen.findByRole('dialog', { name: 'Sửa tài khoản' }))
    await userEvent.type(dlg.getByLabelText('Email đăng nhập'), 'x')
    expect(dlg.getByRole('button', { name: 'Lưu' })).toBeDisabled()
    await userEvent.type(dlg.getByLabelText(/Mã 6 số/), '123456')
    expect(dlg.getByRole('button', { name: 'Lưu' })).toBeEnabled()
  })
})
