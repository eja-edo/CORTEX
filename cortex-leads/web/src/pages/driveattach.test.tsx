import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PickerInfo } from '../api/types'
import { OWNER, CLASS_STAFF, TEACHER, fail, renderApp, server } from '../test/harness'

const picker = vi.hoisted(() => ({ open: vi.fn() }))
vi.mock('../components/drivePicker', async (orig) => ({ ...(await orig<typeof import('../components/drivePicker')>()), openDrivePicker: picker.open }))

beforeEach(() => { picker.open.mockReset() })
afterEach(() => vi.unstubAllGlobals())

const ACCOUNT = { id: 'g1', label: 'Cô Lan', email: 'co.lan@truong.vn', can_pick: true }
const INFO = (o: Partial<PickerInfo> = {}): PickerInfo => ({ configured: true, default_account_id: 'g1', browse: true, accounts: [ACCOUNT], ...o })
const TOKEN = { token: 'ya29.short', expires_in: 3599, api_key: 'AIza-key', app_id: '123456789012', email: 'co.lan@truong.vn' }
const CLASS_G = { id: 'c1', name: 'Tiếng Anh A1', sandbox_id: null, sandbox: '', grader_sandbox_id: 'sb1', account: 'Cô Lan', account_id: 'g1', linked: true, active: true, since: '2026-10-20T02:00:00Z', folder: 'x', folder_url: null,
  owned: false, can_upload: false, webhook: null, has_webhook: false, lessons: { done: 0, failed: 0, waiting: 0, held: 0 }, classroom: { course_id: 'x', course: 'A1', account_id: 'g1' },
  policy: { recap_mode: 'review' as const, grading_mode: 'review' as const, assignment_post_mode: 'manual' as const }, can_grade: true, grading: { assignments: 0, to_review: 0, pending: 0, waiting: 0, done: 0 } }
const FILE = (id: string, name: string) => ({ url: `https://drive.google.com/file/d/${id}/view`, title: name, share: 'VIEW' as const })

const compose = async (session = CLASS_STAFF, extra: Record<string, unknown> = {}) => {
  const s = server({ 'GET /session': session, 'GET /classes': { items: [CLASS_G] }, 'GET /lessons?class_id=c1': { items: [], limit: 100, can_upload: false, max_mb: 1, classes: [] },
    'GET /classes/c1/assignments': { class: { id: 'c1', name: 'Tiếng Anh A1', grading_mode: 'review' }, items: [] }, 'GET /assignments': { items: [], sources: [{ id: 'c1', label: 'Tiếng Anh A1' }] },
    'GET /classes/c1/classroom-options': { topics: [], students: [], problems: {} }, 'GET /class-kinds': { items: [] }, 'GET /google/picker': INFO(), 'POST /google/picker/token': TOKEN, ...extra })
  renderApp('/classes/c1?tab=assignments')
  await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }, { timeout: 5000 }))
  return s
}

describe('Chọn tệp từ Google Drive', () => {
  it('asks for a token for the class\'s account, opens Google\'s dialog with it, and adds what was chosen', async () => {
    const s = await compose()
    picker.open.mockImplementation(async (_cfg, onPick) => onPick([FILE('a1', 'Biểu đồ mẫu.pdf'), FILE('b2', 'Phiếu tuần 3')]))
    expect(await screen.findByText(/Chọn từ Drive của co.lan@truong.vn/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Chọn từ Google Drive/ }))
    await waitFor(() => expect(screen.getByText('Phiếu tuần 3')).toBeInTheDocument())
    expect(s.calls.some((c) => c.path === '/google/picker?class_id=c1')).toBe(true)  // the class's own account is the one to start with
    expect(s.posted('/google/picker/token')[0].body).toEqual({ account_id: 'g1', class_id: 'c1' })
    expect(picker.open).toHaveBeenCalledWith({ token: 'ya29.short', apiKey: 'AIza-key', appId: '123456789012' }, expect.any(Function), true)
    expect(screen.getByText('Biểu đồ mẫu.pdf')).toBeInTheDocument()
    expect(screen.queryByLabelText('Địa chỉ tệp 1')).toBeNull()  // no address box: a file comes from the picker
    expect(screen.getByLabelText('Quyền của học sinh với tệp 1')).toHaveValue('VIEW')  // the teacher can still change what students may do
  })

  it('keeps one of the same file chosen twice', async () => {
    await compose()
    picker.open.mockImplementation(async (_cfg, onPick) => onPick([FILE('a1', 'Biểu đồ mẫu.pdf')]))
    await userEvent.click(await screen.findByRole('button', { name: /Chọn từ Google Drive/ }))
    await screen.findByText('Biểu đồ mẫu.pdf')
    await userEvent.click(screen.getByRole('button', { name: /Chọn từ Google Drive/ }))
    await waitFor(() => expect(picker.open).toHaveBeenCalledTimes(2))
    expect(screen.getAllByText('Biểu đồ mẫu.pdf')).toHaveLength(1)
  })

  it('lets the person choose among several accounts and asks for a token for the one chosen', async () => {
    const s = await compose(CLASS_STAFF, { 'GET /google/picker': INFO({ accounts: [ACCOUNT, { id: 'g2', label: 'Thầy Minh', email: 'minh@truong.vn', can_pick: true }, { id: 'g3', label: 'Chỉ Classroom', email: null, can_pick: false }] }) })
    await userEvent.selectOptions(await screen.findByLabelText('Tài khoản Drive'), 'g2')
    expect(screen.queryByRole('option', { name: /Chỉ Classroom/ })).toBeNull()  // an account without the Drive permission is not offered
    await userEvent.click(screen.getByRole('button', { name: /Chọn từ Google Drive/ }))
    await waitFor(() => expect(s.posted('/google/picker/token')[0].body).toEqual({ account_id: 'g2', class_id: 'c1' }))
  })

  it('opens the upload alone for someone the server says may not browse the account', async () => {
    await compose(TEACHER, { 'GET /google/picker': INFO({ browse: false }) })
    await userEvent.click(await screen.findByRole('button', { name: 'Tải tệp từ máy lên' }))
    await waitFor(() => expect(picker.open).toHaveBeenCalledWith({ token: 'ya29.short', apiKey: 'AIza-key', appId: '123456789012' }, expect.any(Function), false))
  })

  it('says so when the server has not switched the picker on, and offers no other way to attach', async () => {
    await compose(CLASS_STAFF, { 'GET /google/picker': INFO({ configured: false }) })
    expect(await screen.findByText(/Chưa bật chọn tệp từ Google Drive/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chọn từ Google Drive/ })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Tải tệp từ máy/ })).toBeNull()  // the picker is the only way to attach
    expect(screen.queryByRole('button', { name: /Dán địa chỉ/ })).toBeNull()
  })

  it('tells staff to ask the owner, and the owner where to reconnect, when no account has the Drive permission', async () => {
    const none = INFO({ default_account_id: null, accounts: [{ ...ACCOUNT, can_pick: false }] })
    await compose(CLASS_STAFF, { 'GET /google/picker': none })
    expect(await screen.findByText(/Nhờ chủ trung tâm kết nối lại Google/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Kết nối lại Google' })).toBeNull()
    expect(screen.getByRole('button', { name: /Chọn từ Google Drive/ })).toBeDisabled()
  })

  it('offers the owner a link to reconnect', async () => {
    await compose(OWNER, { 'GET /google/picker': INFO({ default_account_id: null, accounts: [{ ...ACCOUNT, can_pick: false }] }) })
    expect(await screen.findByRole('link', { name: 'Kết nối lại Google' })).toHaveAttribute('href', '/settings?tab=google')
  })

  it('shows the server\'s reason when the token cannot be had, and does not open the dialog', async () => {
    await compose(CLASS_STAFF, { 'POST /google/picker/token': fail(409, { code: 'UNAUTHENTICATED', message: 'Phiên kết nối Google của tài khoản này đã hết hạn. Hãy kết nối lại Google' }) })
    await userEvent.click(await screen.findByRole('button', { name: /Chọn từ Google Drive/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/đã hết hạn/)
    expect(picker.open).not.toHaveBeenCalled()
  })

  it('takes a chosen file off again', async () => {
    await compose()
    picker.open.mockImplementation(async (_cfg, onPick) => onPick([FILE('a1', 'Biểu đồ mẫu.pdf'), FILE('b2', 'Phiếu tuần 3')]))
    await userEvent.click(await screen.findByRole('button', { name: /Chọn từ Google Drive/ }))
    await screen.findByText('Phiếu tuần 3')
    await userEvent.click(screen.getByRole('button', { name: 'Bỏ tệp 1' }))
    expect(screen.queryByText('Biểu đồ mẫu.pdf')).toBeNull()
    expect(screen.getByText('Phiếu tuần 3')).toBeInTheDocument()
  })

  it('says Google\'s dialog could not be loaded when it cannot', async () => {
    await compose()
    picker.open.mockImplementation(async () => { throw new Error('PICKER_LOAD_FAILED') })
    await userEvent.click(await screen.findByRole('button', { name: /Chọn từ Google Drive/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/Không mở được hộp chọn tệp của Google/)
  })

  it('is on the template form too, and the chosen file is saved with the template', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /class-kinds': { items: [{ id: 'k1', name: 'IELTS', templates: 0 }] }, 'GET /class-kinds/k1/templates': { kind: { id: 'k1', name: 'IELTS' }, items: [] },
      'GET /google/picker': INFO(), 'POST /google/picker/token': TOKEN, 'POST /class-kinds/k1/templates': {} })
    picker.open.mockImplementation(async (_cfg, onPick) => onPick([FILE('a1', 'Biểu đồ mẫu.pdf')]))
    renderApp('/templates')
    await userEvent.click(await screen.findByRole('button', { name: /Thêm bài tập mẫu/ }))
    await userEvent.click(await screen.findByRole('button', { name: /Chọn từ Google Drive/ }))
    await waitFor(() => expect(screen.getByText('Biểu đồ mẫu.pdf')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: /Dán địa chỉ/ })).toBeNull()
    expect(s.calls.some((c) => c.path === '/google/picker')).toBe(true)  // no class here: the first account that can
    await userEvent.type(screen.getByLabelText('Tên bài tập mẫu'), 'Writing task 1')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bài tập mẫu' }))
    await waitFor(() => expect(s.posted('/class-kinds/k1/templates')).toHaveLength(1))
    expect(s.posted('/class-kinds/k1/templates')[0].body).toMatchObject({ materials: [{ url: 'https://drive.google.com/file/d/a1/view', title: 'Biểu đồ mẫu.pdf', share: 'VIEW' }] })
  })
})
