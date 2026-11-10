import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Member } from '../api/types'
import { OWNER, TEACHER, renderApp, server } from '../test/harness'

const CLASS = { id: 'c1', name: 'Lớp A1', sandbox_id: 'sb2', sandbox: 'Tổng kết', grader_sandbox_id: 'sb1', account: 'Google chung', account_id: 'g1', linked: true, active: true, since: '2026-10-20T02:00:00Z',
  folder: 'Do Cortex tạo trong Drive', folder_url: null, owned: true, can_upload: true, webhook: 'webhook.mezon.ai', has_webhook: true, classroom: { course_id: '111', course: 'Lớp A1', account_id: 'g1' },
  policy: { recap_mode: 'review', grading_mode: 'review', assignment_post_mode: 'manual' }, can_grade: true,
  lessons: { done: 1, failed: 0, waiting: 0, held: 0 }, grading: { assignments: 0, to_review: 0, pending: 0, waiting: 0, done: 0 } }
const LESSONS = { items: [], limit: 100, can_upload: true, max_mb: 500, classes: [{ id: 'c1', name: 'Lớp A1', can_upload: true, lessons: 1 }] }
const CLASSES = { items: [CLASS] }
const U = (o: Partial<Member>): Member => ({ id: 'u1', email: 'mai@trungtam.vn', name: 'Cô Mai', role: 'teacher', staff_ref: 'mai', status: 'active', invited: false, phone: null, birth_date: null, national_id: null, mfa: false, last_login_at: null,
  created_at: '2026-10-20T02:00:00Z', sessions: 0, you: false, classes: [], ...o })
const links = () => within(screen.getByRole('navigation', { name: 'Điều hướng chính' })).getAllByRole('link').map((a) => a.textContent)

describe('a teacher in the console', () => {
  it('starts at their classes, and the menu holds nothing of the rest of the business', async () => {
    server({ 'GET /session': TEACHER, 'GET /classes': CLASSES })
    renderApp('/')
    expect(await screen.findByRole('heading', { name: 'Lớp học' })).toBeInTheDocument()
    await waitFor(() => expect(links().join()).toContain('Lớp học'))
    for (const gone of ['Hộp thư', 'Kỹ năng', 'Sandbox', 'Dữ liệu', 'Nhân viên & quyền']) expect(links().join()).not.toContain(gone)
    for (const soon of ['Việc hôm nay', 'Báo cáo', 'Cài đặt']) expect(screen.queryByText(soon)).toBeNull()
  })

  for (const page of ['/inbox', '/skills', '/sandboxes']) {
    it(`goes back to their classes from ${page} instead of a wall of refusals`, async () => {
      const s = server({ 'GET /session': TEACHER, 'GET /classes': CLASSES })
      renderApp(page)
      expect(await screen.findByRole('heading', { name: 'Lớp học' })).toBeInTheDocument()
      expect(s.calls.map((c) => c.path).join()).not.toMatch(/conversations|skills|sandboxes/)
    })
  }

  it('says so plainly before they have been given a class', async () => {
    server({ 'GET /session': TEACHER, 'GET /classes': { items: [] } })
    renderApp('/classes')
    expect(await screen.findByText(/Bạn chưa được giao lớp nào/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Thêm lớp/ })).toBeNull()
  })

  it('edits what is theirs in a class: no Google, no webhook, no switching off, no writing grades by itself', async () => {
    const s = server({ 'GET /session': TEACHER, 'GET /classes': CLASSES, 'GET /lessons?class_id=c1': LESSONS, 'PATCH /classes/c1': CLASS })
    renderApp('/classes/c1')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    expect(screen.queryByRole('button', { name: 'Thêm thao tác' })).toBeNull()
    expect(within(dialog).queryByText(/Webhook/)).toBeNull()
    expect(within(dialog).queryByRole('button', { name: 'Bỏ webhook riêng' })).toBeNull()
    expect(s.calls.some((c) => c.path.startsWith('/google'))).toBe(false)  // the owner's list of Google accounts is not asked for
    await userEvent.click(within(dialog).getByRole('button', { name: 'Đổi cách chấm bài tập' }))
    const choices = await screen.findByRole('radiogroup', { name: 'Chấm bài tập' })
    expect(within(choices).getAllByRole('radio')).toHaveLength(2)
    expect(within(choices).queryByText('AI chấm và tự ghi điểm')).toBeNull()
    await userEvent.click(within(choices).getByText('Thủ công'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ grading_mode: 'manual' }))
  })

  it('still shows a class the owner set to write grades by itself, in words', async () => {
    const auto = { ...CLASS, policy: { ...CLASS.policy, grading_mode: 'auto_write' } }
    server({ 'GET /session': TEACHER, 'GET /classes': { items: [auto] }, 'GET /lessons?class_id=c1': LESSONS })
    renderApp('/classes/c1')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    expect(await within(await screen.findByRole('dialog', { name: 'Sửa lớp' })).findByText('AI chấm và tự ghi điểm')).toBeInTheDocument()
  })

  it('reads the shared templates and cannot change them', async () => {
    server({ 'GET /session': TEACHER, 'GET /class-kinds': { items: [{ id: 'k1', name: 'IELTS', templates: 1 }] },
      'GET /class-kinds/k1/templates': { kind: { id: 'k1', name: 'IELTS' }, items: [{ id: 't1', kind_id: 'k1', name: 'Mẫu 1', title: null, description: null, max_points: null, criteria: [], answer_key: null, check_prompt: null, language: null, topic_name: null, materials: [], created_by: null, created_at: '2026-10-20T02:00:00Z' }] } })
    renderApp('/templates')
    expect(await screen.findByText('Mẫu 1')).toBeInTheDocument()
    for (const name of [/Thêm bài tập mẫu/, 'Sửa', 'Xoá Mẫu 1', 'Thêm']) expect(screen.queryByRole('button', { name })).toBeNull()
    expect(screen.queryByLabelText('Tên loại lớp mới')).toBeNull()
  })
})

describe('the owner gives classes', () => {
  const page = (u: Member, more = {}) => server({ 'GET /session': OWNER, 'GET /team': { min_password: 10, items: [u] }, 'GET /classes': { items: [CLASS, { ...CLASS, id: 'c2', name: 'Lớp B2' }] }, ...more })

  it('offers the role when adding a person', async () => {
    const s = page(U({}), { 'POST /team': { id: 'u9', email: 'moi@trungtam.vn', staff_ref: 'moi', mail_sent: true, kind: 'invite' } })
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Tạo tài khoản' }))
    await userEvent.type(await screen.findByLabelText('Họ tên'), 'Cô Mới')
    await userEvent.type(screen.getByLabelText('Email'), 'moi@trungtam.vn')
    await userEvent.selectOptions(screen.getByLabelText('Vai trò'), 'teacher')
    await userEvent.click(screen.getByRole('button', { name: /Gửi lời mời/ }))
    await waitFor(() => expect(s.posted('/team')[0].body).toEqual({ email: 'moi@trungtam.vn', name: 'Cô Mới', role: 'teacher' }))
  })

  it('ticks a teacher\'s classes and saves them as one list', async () => {
    const s = page(U({ classes: [{ id: 'c1', name: 'Lớp A1' }] }), { 'PUT /team/u1/classes': U({ classes: [{ id: 'c1', name: 'Lớp A1' }, { id: 'c2', name: 'Lớp B2' }] }) })
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const save = await screen.findByRole('button', { name: 'Lưu thay đổi' })
    expect(save).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'Bỏ Lớp A1' })).toBeInTheDocument() // given classes sit on top as chips
    await userEvent.click(screen.getByRole('button', { name: /Thêm lớp/ }))
    expect(await screen.findByRole('checkbox', { name: 'Lớp A1' })).toBeChecked()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Tìm lớp' }), 'b2')  // the search narrows the list
    expect(screen.queryByRole('checkbox', { name: 'Lớp A1' })).toBeNull()
    await userEvent.click(screen.getByRole('checkbox', { name: 'Lớp B2' }))
    await userEvent.click(save)
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PUT')?.body).toEqual({ class_ids: ['c1', 'c2'] }))
  })

  it('says a teacher without a class sees nothing yet, and asks nothing of a staff member', async () => {
    page(U({}))
    renderApp('/team')
    expect(await screen.findByText('Chưa giao lớp')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Sửa' }))
    expect(await screen.findByText(/Chưa chọn lớp nào/)).toBeInTheDocument()
  })

  it('moves a person from staff to teacher and gives their classes in the same form', async () => {
    const s = page(U({ role: 'staff' }), { 'PATCH /team/u1': U({}), 'PUT /team/u1/classes': U({ classes: [{ id: 'c2', name: 'Lớp B2' }] }) })
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.queryByText('Lớp phụ trách')).toBeNull() // a staff member has every class: nothing to give
    await userEvent.selectOptions(dlg.getByLabelText('Vai trò'), 'teacher')
    expect(await dlg.findByText('Lớp phụ trách')).toBeInTheDocument() // the boxes show as soon as the role says teacher, before it is saved
    await userEvent.click(await dlg.findByRole('button', { name: /Thêm lớp/ }))
    await userEvent.click(await dlg.findByRole('checkbox', { name: 'Lớp B2' }))
    await userEvent.click(dlg.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ role: 'teacher' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PUT')?.body).toEqual({ class_ids: ['c2'] }))
    expect(s.calls.findIndex((c) => c.method === 'PATCH')).toBeLessThan(s.calls.findIndex((c) => c.method === 'PUT')) // the role first
  })

  it('picks the classes while creating a teacher', async () => {
    const s = page(U({}), { 'POST /team': { id: 'u9', email: 'moi@trungtam.vn', staff_ref: 'moi', mail_sent: true, kind: 'invite' }, 'PUT /team/u9/classes': U({ id: 'u9' }) })
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Tạo tài khoản' }))
    const dlg = within(await screen.findByRole('dialog'))
    expect(dlg.queryByText('Lớp phụ trách')).toBeNull()
    await userEvent.type(dlg.getByLabelText('Họ tên'), 'Cô Mới')
    await userEvent.type(dlg.getByLabelText('Email'), 'moi@trungtam.vn')
    await userEvent.selectOptions(dlg.getByLabelText('Vai trò'), 'teacher')
    await userEvent.click(await dlg.findByRole('button', { name: /Thêm lớp/ }))
    await userEvent.click(await dlg.findByRole('checkbox', { name: 'Lớp A1' }))
    await userEvent.click(dlg.getByRole('button', { name: /Gửi lời mời/ }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PUT')?.body).toEqual({ class_ids: ['c1'] }))
    expect(s.posted('/team')[0].body).toEqual({ email: 'moi@trungtam.vn', name: 'Cô Mới', role: 'teacher' })
  })

  it('removes a class with the × on its chip and empties the list with «Bỏ chọn»', async () => {
    const s = page(U({ classes: [{ id: 'c1', name: 'Lớp A1' }, { id: 'c2', name: 'Lớp B2' }] }), { 'PUT /team/u1/classes': U({}) })
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Bỏ Lớp A1' }))
    await userEvent.click(screen.getByRole('button', { name: /Thêm lớp/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Bỏ chọn' }))
    expect(screen.queryByRole('button', { name: 'Bỏ Lớp B2' })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PUT')?.body).toEqual({ class_ids: [] }))
  })

  it('keeps the personal details and the role in two frames of their own', async () => {
    page(U({ role: 'staff' }))
    renderApp('/team')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dlg = within(await screen.findByRole('dialog'))
    const personal = within(dlg.getByRole('group', { name: 'Thông tin cá nhân' }))
    for (const l of ['Họ và tên', 'Ngày sinh', 'Số CCCD', /^Email đăng nhập/, 'Số điện thoại']) expect(personal.getByLabelText(l)).toBeInTheDocument()
    expect(within(dlg.getByRole('group', { name: 'Phân quyền' })).getByLabelText(/^Vai trò/)).toBeInTheDocument()
  })
})
