import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LessonDetail, LessonItem, LessonList } from '../api/types'
import { OWNER, CLASS_STAFF, fail, renderApp, server } from '../test/harness'

const ITEM: LessonItem = { storage: 'drive', origin: 'Google Drive', has_media: true, media_type: 'video', language: null, id: 'l1', name: 'Lớp A1 - buổi 5.mp4', status: 'done', status_label: 'Xong', attempts: 1, sandbox: 'Tổng kết buổi học',
  created_at: '2026-10-22T02:00:00Z', finished_at: '2026-10-22T02:30:00Z', has_recap: true, problem: null, class_id: 'c1', class_name: 'Lớp A1', released: true, released_at: '2026-10-22T02:31:00Z', released_by: 'auto', awaiting_release: false, classroom: null }
const LIST: LessonList = { limit: 100, can_upload: true, max_mb: 1024, classes: [{ id: 'c1', name: 'Lớp A1', can_upload: true, lessons: 2 }], items: [ITEM, { ...ITEM, id: 'l2', name: 'hỏng.mp4', status: 'failed', status_label: 'Thất bại', has_recap: false, problem: 'AI trả lời sai khuôn, sẽ thử lại' }] }
const DETAIL: LessonDetail = { ...ITEM, message: 'x', transcript: 'lời của cả lớp', video_url: 'https://drive.google.com/file/d/abc/view',
  recap: { summary: 'Lớp học thì hiện tại hoàn thành.', topics: ['Thì hiện tại hoàn thành'], homework: [{ task: 'Bài 3 và bài 4 trang 45', due: 'thứ Sáu' }], class_notes: 'Cả lớp theo kịp bài.' } }

/** A stand-in for XMLHttpRequest: records each request to Google and lets the test answer it. */
class FakeXHR {
  static all: FakeXHR[] = []
  static get last() { return FakeXHR.all[FakeXHR.all.length - 1] }
  method = ''; url = ''; headers: Record<string, string> = {}; body: unknown = null; status = 0; responseHeaders: Record<string, string> = {}
  upload = { onprogress: null as null | ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) }
  onload: (() => void) | null = null; onerror: (() => void) | null = null; withCredentials = false
  constructor() { FakeXHR.all.push(this) }
  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader(k: string, v: string) { this.headers[k] = v }
  getResponseHeader(k: string) { return this.responseHeaders[k] ?? null }
  send(body: unknown) { this.body = body }
  answer(status: number, headers: Record<string, string> = {}) { this.status = status; this.responseHeaders = headers; this.onload?.() }
}
beforeEach(() => { FakeXHR.all = [] })
afterEach(() => vi.unstubAllGlobals())
const recording = (name = 'Lớp A1 - buổi 7.mp4', size = 10) => { const f = new File(['0123456789'], name, { type: 'video/mp4' }); Object.defineProperty(f, 'size', { value: size }); return f }
const TICKET = { name: 'Lớp A1 - buổi 7.mp4', upload_url: 'https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&upload_id=U1', chunk_bytes: 4 }
const nextRequest = async (n: number) => { await waitFor(() => expect(FakeXHR.all.length).toBe(n)); return FakeXHR.all[n - 1] }

const CLASS = { id: 'c1', name: 'Lớp A1', sandbox_id: 'sb2', sandbox: 'Tổng kết buổi học', account: 'Google của cô Lan', account_id: 'g1', linked: true, active: true, since: '2026-10-20T02:00:00Z',
  folder: 'Do Cortex tạo trong Drive', folder_url: 'https://drive.google.com/drive/folders/abc', owned: true, can_upload: true, webhook: 'webhook.mezon.ai', has_webhook: true, lessons: { done: 3, failed: 0, waiting: 1, held: 0 }, classroom: null,
  grader_sandbox_id: null, policy: { recap_mode: 'review' as const, grading_mode: 'review' as const, assignment_post_mode: 'manual' as const }, can_grade: false, grading: { assignments: 0, to_review: 0, pending: 0, waiting: 0, done: 0 } }
const CLASS_B = { ...CLASS, id: 'c2', name: 'Lớp B2', webhook: null, has_webhook: false, owned: false, can_upload: false, lessons: { done: 0, failed: 0, waiting: 0, held: 0 } }
const GOOGLE = { configured: true, sources: [], kinds: [], sandboxes: [{ id: 'sb2', title: 'Tổng kết buổi học', purpose: 'lesson_recap' }],
  items: [{ id: 'g1', label: 'Google của cô Lan', email: null, status: 'active', can: { classroom: false, classroom_post: true, classroom_create: false, drive: true, drive_read: false }, connected_at: new Date().toISOString(), connected_by: 'x', used_by: [], refs: [] }] }
const PAGE = '/classes/c1'

describe('Danh sách lớp', () => {
  it('shows each class with its state, its recaps and its webhook, and opens one', async () => {
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS, CLASS_B] }, 'GET /lessons?class_id=c1': LIST, 'GET /lessons': LIST })
    renderApp('/classes')
    expect(await screen.findByRole('link', { name: 'Lớp A1' })).toHaveAttribute('href', '/classes/c1')
    expect(screen.getByText('Webhook: webhook.mezon.ai')).toBeInTheDocument()
    expect(screen.getByText('Dùng kênh chung')).toBeInTheDocument()
    expect(screen.getByText('1 đang chờ')).toBeInTheDocument()
  })

  it('searches classes by name without caring for accents', async () => {
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS, { ...CLASS_B, name: 'Đàm thoại' }] } })
    renderApp('/classes')
    await screen.findByRole('link', { name: 'Lớp A1' })
    await userEvent.type(screen.getByLabelText('Tìm lớp'), 'dam thoai')
    expect(screen.queryByRole('link', { name: 'Lớp A1' })).toBeNull()
    expect(screen.getByRole('link', { name: 'Đàm thoại' })).toBeInTheDocument()
    await userEvent.clear(screen.getByLabelText('Tìm lớp'))
    await userEvent.type(screen.getByLabelText('Tìm lớp'), 'zzz')
    expect(screen.getByText(/Không có lớp nào khớp/)).toBeInTheDocument()
  })

  it('gives staff the list only: no add, edit or delete', async () => {
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS] } })
    renderApp('/classes')
    await screen.findByRole('link', { name: 'Lớp A1' })
    for (const name of ['Thêm lớp', 'Sửa', 'Thêm thao tác']) expect(screen.queryByRole('button', { name })).toBeNull()
  })

  it('says what to do when there is no class', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [] } })
    renderApp('/classes')
    expect(await screen.findByText(/Chưa có lớp nào/)).toBeInTheDocument()
  })

  it('lets the owner add a class with its own folder and webhook, and change a webhook later', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS, CLASS_B] }, 'GET /google/accounts': GOOGLE,
      'POST /classes': { id: 'c3', name: 'Lớp C3' }, 'PATCH /classes/c2': { ...CLASS_B, has_webhook: true, webhook: 'webhook.mezon.ai' } })
    renderApp('/classes')
    await screen.findByRole('link', { name: 'Lớp A1' })
    await userEvent.click(screen.getByRole('button', { name: 'Thêm lớp' }))
    await userEvent.type(await screen.findByLabelText('Tên lớp'), 'Lớp C3')
    await userEvent.click(screen.getByRole('button', { name: /Kênh Mezon riêng/ }))
    await userEvent.type(screen.getByLabelText(/Webhook Mezon của lớp/), 'https://webhook.mezon.ai/hooks/x')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo lớp' }))
    await waitFor(() => expect(s.posted('/classes')[0]?.body).toEqual({ sandbox_id: 'sb2', account_id: 'g1', name: 'Lớp C3', folder: 'new', webhook_url: 'https://webhook.mezon.ai/hooks/x' }))
    const row = screen.getByRole('link', { name: 'Lớp B2' }).closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    await userEvent.type(within(dialog).getByLabelText(/Webhook mới/), 'https://webhook.mezon.ai/hooks/b')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ webhook_url: 'https://webhook.mezon.ai/hooks/b' }))
  })

  it('makes the folder, the Classroom course and the grading in one go, and shows the links', async () => {
    const all = { ...GOOGLE, sandboxes: [...GOOGLE.sandboxes, { id: 'sb9', title: 'Chấm bài', purpose: 'classroom_grader' }],
      items: [{ ...GOOGLE.items[0], can: { classroom: true, classroom_post: true, classroom_create: true, drive: true, drive_read: false } }] }
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'GET /google/accounts': all,
      'POST /classes': { id: 'c3', name: 'IELTS 6.5', folder_url: 'https://drive.google.com/drive/folders/f1', grading: true,
        classroom: { course_id: '99', course: 'IELTS 6.5', url: 'https://classroom.google.com/c/99', created: true } } })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm lớp' }))
    await userEvent.type(await screen.findByLabelText('Tên lớp'), 'IELTS 6.5')
    expect(screen.getByRole('radio', { name: /Tạo lớp mới/ })).toBeChecked()  // everything is made unless the owner says otherwise
    expect(screen.getByLabelText(/AI chấm bài tập của lớp này/)).toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: 'Tạo lớp' }))
    await waitFor(() => expect(s.posted('/classes')[0]?.body).toEqual({ sandbox_id: 'sb2', account_id: 'g1', name: 'IELTS 6.5', folder: 'new', classroom_new: true, grade_sandbox_id: 'sb9' }))
    expect(await screen.findByText(/Lớp «IELTS 6.5» đã được tạo trên Google Classroom/)).toBeInTheDocument()
    const done = within(screen.getByRole('dialog', { name: 'Thêm lớp' }))
    expect(done.getByRole('link', { name: /Mở Classroom/ })).toHaveAttribute('href', 'https://classroom.google.com/c/99')
    expect(done.getByRole('link', { name: /Mở thư mục/ })).toHaveAttribute('href', 'https://drive.google.com/drive/folders/f1')
  })

  it('does not offer to make a course when the account was not given that permission, and says where to fix it', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'GET /google/accounts': GOOGLE })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm lớp' }))
    await screen.findByLabelText('Tên lớp')
    expect(screen.getByRole('radio', { name: /Tạo lớp mới/ })).toBeDisabled()
    expect(screen.getByRole('radio', { name: /Không dùng/ })).toBeChecked()
    expect(screen.getByRole('link', { name: /Cấp quyền ở Cài đặt/ })).toBeInTheDocument()
  })

  it('lets the owner choose the Classroom course a class posts its recaps to', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'GET /google/accounts': GOOGLE, 'GET /google/accounts/g1/courses': { items: [{ id: '777', name: 'IELTS A1', section: 'Sáng', connected: false }] },
      'PATCH /classes/c1': { ...CLASS, classroom: { course_id: '777', course: 'IELTS A1', account_id: 'g1' } } })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    await userEvent.selectOptions(await within(dialog).findByLabelText('Lớp Classroom'), '777')
    expect(within(dialog).queryByLabelText(/Đăng công khai ngay/)).toBeNull()  // whether a recap waits for a person is the class's recap mode, not a tick on the course
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ classroom_account_id: 'g1', classroom_course_id: '777', classroom_course_name: 'IELTS A1' }))
  })

  it('points to the Google settings when no account may post to Classroom yet', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'GET /google/accounts': { ...GOOGLE, items: [{ ...GOOGLE.items[0], can: { ...GOOGLE.items[0].can, classroom_post: false } }] } })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    expect(await within(dialog).findByRole('link', { name: 'Kết nối tài khoản Google' })).toHaveAttribute('href', '/settings')
  })

  it('tells a class whose Google account was deleted, and links it to another account and folder', async () => {
    const orphan = { ...CLASS, account: null, account_id: null, linked: false, can_upload: false }
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [orphan] }, 'GET /lessons?class_id=c1': LIST, 'GET /lessons': LIST, 'GET /google/accounts': GOOGLE,
      'POST /classes/c1/relink': { ...CLASS } })
    renderApp(PAGE)
    expect(await screen.findByText(/Tài khoản Google của lớp đã bị xóa/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Nối lại với Google' }))
    const dialog = await screen.findByRole('dialog', { name: /Nối lại lớp «Lớp A1»/ })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Nối lại' }))
    await waitFor(() => expect(s.posted('/classes/c1/relink')[0].body).toEqual({ account_id: 'g1', folder: 'new' }))
  })

  it('asks before deleting a class and says the Drive folder stays', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'DELETE /classes/c1': { deleted: 'c1', lessons: 4 } })
    renderApp('/classes')
    await screen.findByRole('link', { name: 'Lớp A1' })
    await userEvent.click(screen.getByRole('button', { name: 'Thêm thao tác' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Xóa lớp' }))
    expect(await screen.findByText(/cùng 4 buổi học.*Drive vẫn được giữ nguyên/)).toBeInTheDocument()
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận xóa' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'DELETE' && c.path === '/classes/c1')).toBe(true))
  })
})

describe('Chi tiết lớp', () => {
  const base = { 'GET /classes': { items: [CLASS, CLASS_B] }, 'GET /lessons?class_id=c1': LIST }

  it('says where the recordings are kept and where the recaps go', async () => {
    server({ 'GET /session': CLASS_STAFF, ...base })
    renderApp(PAGE)
    expect(await screen.findByRole('heading', { name: 'Lớp A1' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Mở trong Drive/ })).toHaveAttribute('href', 'https://drive.google.com/drive/folders/abc')
    expect(screen.getByText('webhook.mezon.ai')).toBeInTheDocument()
    expect(screen.queryByText('Google của cô Lan')).toBeNull() // the account and the rest wait behind «Chi tiết kết nối»
    await userEvent.click(screen.getByRole('button', { name: 'Chi tiết kết nối' }))
    expect(screen.getByText('Google của cô Lan')).toBeInTheDocument()
  })

  it('says a class without its own webhook uses the common channel', async () => {
    server({ 'GET /session': CLASS_STAFF, ...base, 'GET /lessons?class_id=c2': { ...LIST, items: [] } })
    renderApp('/classes/c2')
    expect(await screen.findByText('Kênh chung')).toBeInTheDocument()
    expect(screen.getAllByText(/chỉ đọc/).length).toBeGreaterThan(0)
    expect(screen.queryByLabelText('Chọn bản ghi')).toBeNull()  // a folder the teacher already had is read only
  })

  it('lists the files of the class with status and the reason one failed', async () => {
    server({ 'GET /session': CLASS_STAFF, ...base })
    renderApp(PAGE)
    expect(await screen.findByText('Lớp A1 - buổi 5.mp4')).toBeInTheDocument()
    expect(screen.getByText('Thất bại')).toBeInTheDocument()
    expect(screen.getByText('AI trả lời sai khuôn, sẽ thử lại')).toBeInTheDocument()
  })

  it('says so when the folder has no file yet', async () => {
    server({ 'GET /session': CLASS_STAFF, ...base, 'GET /lessons?class_id=c1': { ...LIST, items: [] } })
    renderApp(PAGE)
    expect(await screen.findByText('Thả bản ghi buổi học vào đây')).toBeInTheDocument()
    expect(screen.getByLabelText('Chọn bản ghi')).toBeInTheDocument()
  })

  it('says there is no such class when it was deleted', async () => {
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [] }, 'GET /lessons?class_id=zz': LIST })
    renderApp('/classes/zz')
    expect(await screen.findByText(/Không có lớp này/)).toBeInTheDocument()
  })

  it('lets the owner rename, switch off and delete the class from its page', async () => {
    const s = server({ 'GET /session': OWNER, ...base, 'PATCH /classes/c1': { ...CLASS, active: false }, 'DELETE /classes/c1': { deleted: 'c1', lessons: 4 } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm thao tác' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Tắt lớp' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ active: false }))
    await userEvent.click(screen.getByRole('button', { name: 'Sửa' }))
    expect(within(await screen.findByRole('dialog', { name: 'Sửa lớp' })).getByLabelText('Tên lớp')).toHaveValue('Lớp A1')
    await userEvent.click(screen.getByRole('button', { name: 'Hủy' }))
    await userEvent.click(screen.getByRole('button', { name: 'Thêm thao tác' }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Xóa lớp' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Xác nhận xóa' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'DELETE' && c.path === '/classes/c1')).toBe(true))
    expect(await screen.findByRole('heading', { name: 'Lớp học' })).toBeInTheDocument()  // back to the list
  })
})

describe('Tải lên', () => {
  const up = (over = {}) => ({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS] }, 'GET /lessons?class_id=c1': LIST, ...over })

  it('asks Cortex for a ticket for this class, then sends the recording to Google in chunks, and says it is in the Drive', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    const s = server(up({ 'POST /lessons/upload/session': TICKET }))
    renderApp(PAGE)
    await userEvent.upload(await screen.findByLabelText('Chọn bản ghi'), recording())
    await userEvent.selectOptions(screen.getByLabelText('Ngôn ngữ bản ghi'), 'en')
    await userEvent.click(screen.getByRole('button', { name: 'Tải lên Drive' }))
    const first = await nextRequest(1)
    expect(s.posted('/lessons/upload/session')[0].body).toEqual({ name: 'Lớp A1 - buổi 7.mp4', size: 10, language: 'en', class_id: 'c1' })
    expect(first.method).toBe('PUT')
    expect(first.url).toBe(TICKET.upload_url)
    expect(first.headers['Content-Range']).toBe('bytes 0-3/10')
    expect(Object.keys(first.headers)).toEqual(['Content-Range'])  // no Cortex cookie or token goes to Google
    expect(first.withCredentials).toBe(false)
    first.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 })
    expect(await screen.findByRole('progressbar', { name: 'Tiến độ tải lên' })).toHaveAttribute('aria-valuenow', '20')
    first.answer(308, { Range: 'bytes=0-3' })
    const second = await nextRequest(2)
    expect(second.headers['Content-Range']).toBe('bytes 4-7/10')
    second.answer(308)
    const third = await nextRequest(3)
    expect(third.headers['Content-Range']).toBe('bytes 8-9/10')
    third.answer(200)
    expect(await screen.findByText(/Đã lưu «Lớp A1 - buổi 7.mp4» vào thư mục của lớp/)).toBeInTheDocument()  // processing is the watcher's job
  })

  it('asks Google how much it has after a dropped chunk, and goes on from there', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    server(up({ 'POST /lessons/upload/session': TICKET }))
    renderApp(PAGE)
    await userEvent.upload(await screen.findByLabelText('Chọn bản ghi'), recording())
    await userEvent.click(screen.getByRole('button', { name: 'Tải lên Drive' }))
    ;(await nextRequest(1)).onerror?.()
    const ask = await nextRequest(2)
    expect(ask.headers['Content-Range']).toBe('bytes */10')
    ask.answer(308, { Range: 'bytes=0-3' })  // Google has the first chunk after all
    const again = await nextRequest(3)
    expect(again.headers['Content-Range']).toBe('bytes 4-7/10')
  })

  it('says so when the ticket has expired', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    server(up({ 'POST /lessons/upload/session': TICKET }))
    renderApp(PAGE)
    await userEvent.upload(await screen.findByLabelText('Chọn bản ghi'), recording())
    await userEvent.click(screen.getByRole('button', { name: 'Tải lên Drive' }))
    ;(await nextRequest(1)).answer(410)
    expect(await screen.findByText('Phiên tải lên đã hết hạn. Hãy tải lại từ đầu.')).toBeInTheDocument()
  })

  it('says what Cortex refused, in words, before anything is sent to Google', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXHR)
    server(up({ 'POST /lessons/upload/session': fail(429, { code: 'TOO_MANY', message: 'Hôm nay đã tải lên quá nhiều bản ghi, thử lại vào ngày mai' }) }))
    renderApp(PAGE)
    await userEvent.upload(await screen.findByLabelText('Chọn bản ghi'), recording('ghi.mp3'), { applyAccept: false })
    await userEvent.click(screen.getByRole('button', { name: 'Tải lên Drive' }))
    expect(await screen.findByText('Hôm nay đã tải lên quá nhiều bản ghi, thử lại vào ngày mai')).toBeInTheDocument()
    expect(FakeXHR.all.length).toBe(0)
  })

  it('does not even start for a file over the limit', async () => {
    server(up({ 'GET /lessons?class_id=c1': { ...LIST, max_mb: 5 } }))
    renderApp(PAGE)
    await userEvent.upload(await screen.findByLabelText('Chọn bản ghi'), recording('to.mp4', 9 * 1048576))
    expect(screen.getByRole('button', { name: 'Tải lên Drive' })).toBeDisabled()
    expect(screen.getByText(/vượt giới hạn 5 MB/)).toBeInTheDocument()
  })

  it('offers no upload to a switched off class', async () => {
    server(up({ 'GET /classes': { items: [{ ...CLASS, active: false, can_upload: false }] } }))
    renderApp(PAGE)
    expect(await screen.findByText(/Chưa tải lên được/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Chọn bản ghi')).toBeNull()
  })
})

describe('Nội dung tệp', () => {
  const withMedia = (over: Partial<LessonDetail> = {}) => ({ ...DETAIL, origin: 'Google Drive', storage: 'drive', has_media: true, media_type: 'video', language: 'en', video_url: null, ...over })
  const open = async (detail: LessonDetail | object, role = OWNER) => {
    const s = server({ 'GET /session': role, 'GET /classes': { items: [CLASS] }, 'GET /lessons?class_id=c1': LIST, 'GET /lessons/l1': detail, 'DELETE /lessons/l1': { deleted: 'l1' } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByText('Lớp A1 - buổi 5.mp4'))
    return s
  }

  it('a video lesson has a player on its own recording next to the recap', async () => {
    await open(withMedia())
    const player = (await screen.findByLabelText('Xem lại bản ghi')).querySelector('video')!
    expect(player).toHaveAttribute('src', '/api/v1/lessons/l1/media')
    expect(screen.getByText('Bài 3 và bài 4 trang 45')).toBeInTheDocument()
  })

  it('a sound recording gets an audio player', async () => {
    await open(withMedia({ media_type: 'audio' }))
    expect((await screen.findByLabelText('Xem lại bản ghi')).querySelector('audio')).toHaveAttribute('src', '/api/v1/lessons/l1/media')
  })

  it('opens a recap with the homework and its due date, says it is a draft, and keeps the transcript folded until asked', async () => {
    await open(DETAIL)
    expect(await screen.findByText(/Bản nháp do AI viết từ bản ghi/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Mở tệp trong Drive/ })).toHaveAttribute('href', 'https://drive.google.com/file/d/abc/view')
    expect(screen.getByText(/hạn thứ Sáu/)).toBeInTheDocument()
    expect(screen.queryByText('lời của cả lớp')).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: /Xem bản chữ/ }))
    expect(screen.getByText('lời của cả lớp')).toBeInTheDocument()
  })

  it('says so when there is no homework in the recording', async () => {
    await open({ ...DETAIL, recap: { ...DETAIL.recap!, homework: [] } })
    expect(await screen.findByText('Không có bài tập nào được giao trong bản ghi.')).toBeInTheDocument()
  })

  it('deletes a file after asking, and the panel closes', async () => {
    const s = await open(DETAIL)
    await userEvent.click(await screen.findByRole('button', { name: 'Xóa tệp' }))
    expect(await screen.findByText(/thùng rác của thư mục Drive/)).toBeInTheDocument()
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận xóa' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'DELETE' && c.path === '/lessons/l1')).toBe(true))
    expect(await screen.findByText(/Chọn một tệp để xem lại/)).toBeInTheDocument()
  })

  it('does not offer delete for a file in a read-only folder', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [{ ...CLASS, owned: false, can_upload: false }] }, 'GET /lessons?class_id=c1': LIST, 'GET /lessons/l1': DETAIL })
    renderApp(PAGE)
    await userEvent.click(await screen.findByText('Lớp A1 - buổi 5.mp4'))
    await screen.findByText(/Bản nháp do AI viết/)
    expect(screen.queryByRole('button', { name: 'Xóa tệp' })).toBeNull()
  })

  it('a link from a message opens that lesson in its class', async () => {
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS] }, 'GET /lessons?class_id=c1': LIST, 'GET /lessons/l1': withMedia() })
    renderApp('/lessons/l1')
    expect(await screen.findByLabelText('Xem lại bản ghi')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Lớp A1' })).toBeInTheDocument()
  })
})


describe('Tự động hóa của lớp', () => {
  const GRADING_CLASS = { ...CLASS, can_grade: true, grader_sandbox_id: 'sb3', policy: { recap_mode: 'review' as const, grading_mode: 'review' as const, assignment_post_mode: 'manual' as const },
    grading: { assignments: 2, to_review: 3, pending: 0, waiting: 0, done: 5 } }

  it('shows the two automation rows with their current choice and saves only what changed', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /classes': { items: [GRADING_CLASS] }, 'GET /google/accounts': GOOGLE, 'PATCH /classes/c1': GRADING_CLASS })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    expect(within(dialog).getByText('Chờ duyệt')).toBeInTheDocument()  // recap: waits for a teacher
    expect(within(dialog).getByText('AI chấm, giáo viên duyệt')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: /Đổi cách chấm bài tập/ }))
    const picker = await screen.findByRole('dialog', { name: 'Chấm bài tập' })
    expect(within(picker).getByText(/học sinh không nhận được nhận xét qua Classroom/)).toBeInTheDocument()  // what the grade does and does not reach
    await userEvent.click(within(picker).getByRole('radio', { name: /AI chấm và tự ghi điểm/ }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(s.calls.find((c) => c.method === 'PATCH')?.body).toEqual({ grading_mode: 'auto_write' }))
  })

  it('does not offer to change grading for a class that has no Classroom course to grade', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [CLASS] }, 'GET /google/accounts': GOOGLE })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa lớp' })
    expect(within(dialog).getByText('Chưa nối khoá học Classroom để chấm bài')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: /Đổi cách chấm bài tập/ })).toBeDisabled()
  })

  it('has no per-assignment publishing row: that feature is not built yet', async () => {
    server({ 'GET /session': OWNER, 'GET /classes': { items: [GRADING_CLASS] }, 'GET /google/accounts': GOOGLE })
    renderApp('/classes')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    expect(within(await screen.findByRole('dialog', { name: 'Sửa lớp' })).queryByText(/Đăng bài tập/)).toBeNull()
  })

  it('lets a teacher release a recap that a class holds, and tells where it was held', async () => {
    const held = { ...DETAIL, released: false, released_at: null, released_by: null, awaiting_release: true }
    const s = server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS] }, 'GET /lessons?class_id=c1': { ...LIST, items: [{ ...ITEM, released: false, awaiting_release: true }] }, 'GET /lessons/l1': held, 'POST /lessons/l1/release': { released: 'l1' } })
    renderApp('/classes/c1?file=l1')
    expect(await screen.findByText(/đang chờ giáo viên duyệt/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt và gửi' }))
    await waitFor(() => expect(s.posted('/lessons/l1/release')).toHaveLength(1))
  })

  it('shows the class page with a lessons tab and an assignments tab, previews a made assignment and links to its submissions', async () => {
    const WORKS = { class: { id: 'c1', name: 'Lớp A1', grading_mode: 'review' }, items: [
      { id: 'a1', title: 'Viết 5 câu', state: 'created', ours: true, gradable: true, max_points: 10, due: null, created_at: '2026-10-22T02:00:00Z', submissions: 3, description: 'Viết năm câu về kỳ nghỉ của em.', criteria: [{ id: 'ng', label: 'Ngữ pháp', points: 10, descriptor: '' }], materials: [], answer_key: null, check_prompt: null, language: null,
        counts: { pending: 0, proposed: 2, approved: 1, rejected: 0, skipped: 0, failed: 0, waiting: 0 } }] }
    server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [GRADING_CLASS] }, 'GET /lessons?class_id=c1': LIST, 'GET /classes/c1/assignments': WORKS, 'GET /assignments?class_id=c1': { items: [{ id: 'a1', class_id: 'c1', course: null, title: 'Viết 5 câu', description: 'Viết năm câu về kỳ nghỉ của em.', max_points: 10, criteria: [], answer_key: null, language: null, origin: 'teacher', materials: [], status: 'created', due: null, publish: true, error: null, created_by: null, created_at: '2026-10-22T02:00:00Z' }], sources: [] } })
    renderApp('/classes/c1?tab=assignments')
    const row = await screen.findByRole('button', { name: /Viết 5 câu/ })
    expect(within(row).getByText('2 chờ duyệt')).toBeInTheDocument()
    expect(screen.queryByText('Viết năm câu về kỳ nghỉ của em.')).toBeNull()  // nothing opens until the row is picked
    await userEvent.click(row)
    expect(await screen.findByText('Viết năm câu về kỳ nghỉ của em.')).toBeInTheDocument()
    expect(screen.getByText(/Ngữ pháp: 10 điểm/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Mở chi tiết bài tập/ })).toHaveAttribute('href', '/classes/c1/assignments/a1')
    expect(screen.getByRole('tab', { name: /Bài giảng/ })).toBeInTheDocument()
  })
})
