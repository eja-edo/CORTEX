import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { GoogleAccount, GoogleList } from '../api/types'
import { OWNER, STAFF, renderApp, server } from '../test/harness'

const A = (o: Partial<GoogleAccount> = {}): GoogleAccount => ({ id: 'g1', label: 'Google của cô Lan', email: 'co.lan@truong.vn', status: 'active', can: { classroom: true, classroom_post: false, drive: true, drive_read: false },
  connected_at: new Date().toISOString(), connected_by: 'staff:owner', used_by: [], refs: [], ...o })
const LIST = (o: Partial<GoogleList> = {}): GoogleList => ({ configured: true, items: [A()], sources: [], kinds: [],
  sandboxes: [{ id: 'sb1', title: 'Chấm bài', purpose: 'classroom_grader' }, { id: 'sb2', title: 'Tổng kết buổi học', purpose: 'lesson_recap' }], ...o })

afterEach(() => vi.unstubAllGlobals())

describe('Kết nối Google', () => {
  it('is the owner\'s page only: Cài đặt stays a placeholder for staff', async () => {
    server({ 'GET /session': STAFF, 'GET /conversations?filter=need_human': { items: [], counts: { need_human: 0, waiting: 0, silent: 0, all: 0 } } })
    renderApp('/inbox')
    await screen.findByRole('navigation')
    expect(screen.queryByRole('link', { name: /Cài đặt/ })).toBeNull()
  })

  it('says so when the server cannot sign anyone in, and does not offer the button', async () => {
    server({ 'GET /session': OWNER, 'GET /google/accounts': LIST({ configured: false, items: [] }) })
    renderApp('/settings')
    expect(await screen.findByText(/chưa được cấu hình để đăng nhập Google/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Đăng nhập bằng Google/ })).toBeDisabled()
  })

  it('sends the person to Google with the name and the ticked uses', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const s = server({ 'GET /session': OWNER, 'GET /google/accounts': LIST({ items: [] }), 'POST /google/accounts/connect': { url: 'https://accounts.google.com/o/oauth2/v2/auth?x=1' } })
    renderApp('/settings')
    await userEvent.type(await screen.findByLabelText('Tên gọi'), 'Thầy Minh')
    await userEvent.click(screen.getByLabelText(/Drive: thư mục của lớp/))
    await userEvent.click(screen.getByLabelText(/Đọc thư mục Drive có sẵn/))
    await userEvent.click(screen.getByRole('button', { name: /Đăng nhập bằng Google/ }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?x=1'))
    expect(s.posted('/google/accounts/connect')[0].body).toEqual({ label: 'Thầy Minh', kinds: ['classroom', 'classroom_post'] })
  })

  it('tells what came back from Google', async () => {
    server({ 'GET /session': OWNER, 'GET /google/accounts': LIST() })
    renderApp('/settings?error=DENIED')
    expect(await screen.findByText(/không đồng ý cấp quyền/)).toBeInTheDocument()
  })

  it('shows what each account may do and says what is missing, with nothing about classes', async () => {
    server({ 'GET /session': OWNER, 'GET /google/accounts': LIST() })
    renderApp('/settings')
    const perms = within(await screen.findByRole('list', { name: 'Quyền đã cấp' }))
    expect(perms.getByText('Chấm bài trên Classroom').closest('li')).toHaveTextContent('Đọc lớp và bài nộp')
    expect(perms.getByText('Đăng tổng kết lên Classroom').closest('li')).toHaveTextContent('Chưa cấp')  // classroom_post is false in the fixture
    expect(screen.queryByRole('button', { name: 'Nối lớp Classroom' })).toBeNull()
  })

  it('asks before it disconnects an account and says what will stop', async () => {
    const refs = [{ kind: 'classroom', id: 'c1', name: 'Lớp 6A', active: true, }] as GoogleAccount['refs']
    const s = server({ 'GET /session': OWNER, 'GET /google/accounts': LIST({ items: [A({ refs })] }), 'POST /google/accounts/g1/revoke': A({ status: 'revoked' }) })
    renderApp('/settings')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm thao tác' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Ngắt kết nối' }))
    const dialog = await screen.findByRole('dialog', { name: /Ngắt kết nối «Google của cô Lan»/ })
    expect(within(dialog).getByText(/Lớp 6A/)).toBeInTheDocument()
    expect(s.posted('/google/accounts/g1/revoke')).toHaveLength(0) // a question first
    await userEvent.click(within(dialog).getByRole('button', { name: 'Ngắt kết nối' }))
    await waitFor(() => expect(s.posted('/google/accounts/g1/revoke')).toHaveLength(1))
  })

  it('signs the same account in again without making a new one', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { ...window.location, assign })
    const s = server({ 'GET /session': OWNER, 'GET /google/accounts': LIST({ items: [A({ status: 'revoked' })] }), 'POST /google/accounts/g1/reconnect': { url: 'https://accounts.google.com/o/oauth2/v2/auth?r=1' } })
    renderApp('/settings')
    await userEvent.click(await screen.findByRole('button', { name: 'Kết nối lại' }))
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://accounts.google.com/o/oauth2/v2/auth?r=1'))
    expect(s.posted('/google/accounts/g1/reconnect')[0].body).toEqual({ kinds: ['classroom', 'classroom_post', 'drive', 'drive_read'] })
  })

  it('deletes an account in one confirmation and says what will lose its connection', async () => {
    const refs = [{ kind: 'folder', id: 'f1', name: 'Lớp có thư mục', active: true }] as GoogleAccount['refs']
    const s = server({ 'GET /session': OWNER, 'GET /google/accounts': LIST({ items: [A({ refs })] }), 'DELETE /google/accounts/g1': { deleted: 'g1', sources: 1 } })
    renderApp('/settings')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm thao tác' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Xóa tài khoản' }))
    const dialog = await screen.findByRole('dialog', { name: /Xóa tài khoản «Google của cô Lan»/ })
    expect(within(dialog).getByText(/Lớp có thư mục/)).toHaveTextContent('mất kết nối Google')
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)  // a question first
    await userEvent.click(within(dialog).getByRole('button', { name: 'Xác nhận xóa' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'DELETE' && c.path === '/google/accounts/g1')).toBe(true))
  })
})
