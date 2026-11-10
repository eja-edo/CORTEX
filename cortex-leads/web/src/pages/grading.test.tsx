import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { AssignmentList, GradeDetail, GradeItem, GradeList } from '../api/types'
import { OWNER, CLASS_STAFF, renderApp, server } from '../test/harness'

const picker = vi.hoisted(() => ({ open: vi.fn() }))
vi.mock('../components/drivePicker', async (orig) => ({ ...(await orig<typeof import('../components/drivePicker')>()), openDrivePicker: picker.open }))
beforeEach(() => { picker.open.mockReset() })

const ITEM: GradeItem = { id: 'g1', class_id: 'c1', assignment_id: 'a1', work_title: 'Viết 5 câu', student: 'Nguyễn Minh An', status: 'proposed', status_label: 'Chờ giáo viên duyệt', ours: true, max_points: 10, total: 9,
  flags: [], problems: 1, reason: null, written: false, created_at: '2026-10-22T02:00:00Z' }
const LIST: GradeList = { limit: 100, counts: { pending: 0, proposed: 2, approved: 0, rejected: 0, skipped: 1, failed: 0, waiting: 0 },
  items: [ITEM, { ...ITEM, id: 'g2', student: 'Trần Bảo Châu', flags: ['CONTENT_ADDRESSES_THE_GRADER'], problems: 2 }] }
const DETAIL: GradeDetail = { ...ITEM, content_kind: ['text'], content: 'She has finished her homework. We have never been to Paris.',
  guide: { title: 'Viết 5 câu', max_points: 10, answer_key: null, criteria: [{ id: 'dung_thi', label: 'Dùng đúng thì', points: 6, descriptor: '' }, { id: 'du_so_cau', label: 'Đủ 5 câu', points: 4, descriptor: '' }] },
  proposal: { total: 9, max_points: 10, feedback: 'Em làm tốt.', concerns: ['Bài ngắn'], problems: ['Tiêu chí «Đủ 5 câu»: trích dẫn không có trong bài, điểm đề xuất 4 đặt lại 0.'], flags: [],
    criteria: [{ id: 'dung_thi', label: 'Dùng đúng thì', points: 6, score: 5, proposed: 5, quote: 'She has finished', comment: '', verified: true },
               { id: 'du_so_cau', label: 'Đủ 5 câu', points: 4, score: 0, proposed: 4, quote: 'five sentences', comment: '', verified: false }] },
  final: null, decided_by: null, decided_at: null }
const WORKS = (over: Record<string, unknown> = {}) => ({ class: { id: 'c1', name: 'Tiếng Anh A1', grading_mode: 'review' }, items: [
  { id: 'a1', title: 'Viết 5 câu', state: 'created', ours: true, posting: 'published', topic: null, scheduled: null, assignees: null, gradable: true, max_points: 10, due: null, created_at: '2026-10-22T02:00:00Z', submissions: 3, description: 'Viết năm câu về kỳ nghỉ của em.', criteria: [{ id: 'ng', label: 'Ngữ pháp', points: 10, descriptor: '' }], materials: [], answer_key: null, check_prompt: null, language: null,
    counts: { pending: 0, proposed: 2, approved: 0, rejected: 0, skipped: 1, failed: 0, waiting: 0 }, ...over }] })
const base = (extra: Record<string, unknown> = {}) => server({ 'GET /session': CLASS_STAFF, 'GET /classes/c1/assignments': WORKS(), 'GET /grading': LIST, 'GET /grading/g1': DETAIL, ...extra })
const PAGE = '/classes/c1/assignments/a1'

describe('Bài nộp của một bài tập', () => {
  it('opens on the brief, and the students tab searches by name', async () => {
    base()
    renderApp(PAGE)
    expect(await screen.findByText('Viết năm câu về kỳ nghỉ của em.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Học sinh/ }))
    expect(await screen.findByText('Nguyễn Minh An')).toBeInTheDocument()
    await userEvent.type(screen.getByRole('searchbox', { name: 'Tìm học sinh' }), 'zzz')
    expect(screen.queryByText('Nguyễn Minh An')).toBeNull()
    expect(screen.getByText(/Không có học sinh nào khớp/)).toBeInTheDocument()
  })

  it('lists what waits for a teacher, with the suggested total and a warning on work that asks the grader for marks', async () => {
    base()
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    expect(await screen.findByText('Nguyễn Minh An')).toBeInTheDocument()
    expect(screen.getAllByText('9/10').length).toBe(2)  // one per suggestion
    expect(screen.getByText('Bài có câu xin điểm')).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Chờ duyệt/ })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Viết 5 câu' })).toBeInTheDocument()
    expect(screen.getByText('Cortex tạo · ghi điểm được')).toBeInTheDocument()
  })

  it('shows the work, the guide, each mark with its quote, and says when a quote is not in the work', async () => {
    base()
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    expect(await screen.findByText(/She has finished her homework/)).toBeInTheDocument()
    expect(screen.getByText('Có trong bài')).toBeInTheDocument()
    expect(screen.getByText('Không có trong bài')).toBeInTheDocument()
    expect(screen.getByText(/AI đề xuất 4 nhưng dẫn chứng không có trong bài nên đặt lại 0/)).toBeInTheDocument()
    expect(screen.getByText(/Đề xuất của AI, chưa có hiệu lực/)).toBeInTheDocument()
    expect(screen.getByText(/Lưu ý của AI: Bài ngắn/)).toBeInTheDocument()
  })

  it('the teacher changes a mark, the total follows, and a mark above its points cannot be approved', async () => {
    base()
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    const field = await screen.findByLabelText('Điểm Dùng đúng thì')
    await userEvent.clear(field)
    await userEvent.type(field, '4')
    expect(screen.getByText('Tổng: 4 / 10')).toBeInTheDocument()
    await userEvent.clear(field)
    await userEvent.type(field, '7')
    expect(screen.getByRole('button', { name: 'Duyệt điểm' })).toBeDisabled()
  })

  it('approving sends the teachers marks and no choice of where to write: that is the class policy', async () => {
    const s = base({ 'POST /grading/g1/decision': { status: 'approved', total: 4, written: true } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    const field = await screen.findByLabelText('Điểm Dùng đúng thì')
    await userEvent.clear(field)
    await userEvent.type(field, '4')
    expect(screen.queryByRole('radio')).toBeNull()
    expect(screen.getByText(/Duyệt là ghi điểm này lên Classroom và trả bài cho học sinh/)).toBeInTheDocument()
    expect(screen.getByText(/học sinh không nhận được nhận xét qua Classroom/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt điểm' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'POST')).toBe(true))
    const body = s.calls.find((c) => c.method === 'POST')!.body as Record<string, unknown>
    expect(body).toMatchObject({ action: 'approve', scores: { dung_thi: 4, du_so_cau: 0 } })
    expect(body).not.toHaveProperty('write')
  })

  it('says what the work was read from, and warns when it was a recording turned into text', async () => {
    base({ 'GET /grading/g1': { ...DETAIL, content_kind: ['audio'], content: '[Bản chép lời từ bản ghi âm, do máy nhận dạng nên có thể sai]\nI have two brothers.',
      proposal: { ...DETAIL.proposal!, problems: ['Bài nộp là âm thanh được máy chép lại thành chữ. Lỗi nhận dạng có thể bị tính nhầm thành lỗi của học sinh; hãy nghe lại bản ghi trước khi duyệt.'] } } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    expect(await screen.findByText('Âm thanh (bản chép lời)')).toBeInTheDocument()
    expect(screen.getByText(/hãy nghe lại bản ghi trước khi duyệt/)).toBeInTheDocument()
  })

  it('work we did not create says the grade stays here for the teacher to type in', async () => {
    base({ 'GET /grading/g1': { ...DETAIL, ours: false } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    expect(await screen.findByText(/không do ứng dụng tạo nên Google không cho ghi điểm/)).toBeInTheDocument()
    expect(screen.queryByText(/Duyệt là ghi điểm này lên Classroom/)).toBeNull()
  })

  it('a submission waiting in manual mode is asked of the AI with a click, one or all', async () => {
    const pending = { ...ITEM, status: 'pending' as const, status_label: 'Chờ giáo viên bấm chấm', total: null, problems: 0 }
    const s = server({ 'GET /session': CLASS_STAFF, 'GET /classes/c1/assignments': WORKS({ counts: { pending: 2, proposed: 0, approved: 0, rejected: 0, skipped: 0, failed: 0, waiting: 0 } }),
      'GET /grading': { ...LIST, counts: { ...LIST.counts, proposed: 0, pending: 2 }, items: [pending, { ...pending, id: 'g2', student: 'Trần Bảo Châu' }] },
      'GET /grading/g1': { ...DETAIL, ...pending, proposal: null }, 'POST /grading/g1/grade': { queued: 1 }, 'POST /assignments/a1/grade': { queued: 2 } })
    renderApp(`${PAGE}?item=g1`)
    await userEvent.click(await screen.findByRole('button', { name: 'Chấm bằng AI' }))
    await waitFor(() => expect(s.posted('/grading/g1/grade')).toHaveLength(1))
    await userEvent.click(screen.getByRole('button', { name: /Chấm bằng AI cả 2 bài/ }))
    await waitFor(() => expect(s.posted('/assignments/a1/grade')).toHaveLength(1))
  })

  it('a grade the AI wrote by itself says so', async () => {
    base({ 'GET /grading/g1': { ...DETAIL, status: 'approved', status_label: 'Đã duyệt', written: true, decided_by: 'auto', decided_at: '2026-10-22T03:00:00Z', proposal: DETAIL.proposal,
      final: { scores: { dung_thi: 5, du_so_cau: 0 }, total: 5, max_points: 10, write: 'return', feedback: 'Em làm tốt.' } } })
    renderApp(`${PAGE}?item=g1`)
    expect(await screen.findByText('Tự động ghi lên Classroom')).toBeInTheDocument()
  })

  it('a refusal from the server is shown in words', async () => {
    base({ 'POST /grading/g1/decision': { __status: 409, body: { detail: { code: 'ALREADY_DECIDED', message: 'Mục này đã được quyết định rồi' } } } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    await userEvent.click(await screen.findByText('Nguyễn Minh An'))
    await userEvent.click(await screen.findByRole('button', { name: 'Duyệt điểm' }))
    expect(await screen.findByText('Mục này đã được quyết định rồi')).toBeInTheDocument()
  })

  it('a link from a message opens that submission straight away, whatever tab it would be on', async () => {
    base({ 'GET /grading': { ...LIST, items: [] } })
    renderApp('/grading/g1')  // the address a team message carries: it lands on the assignment's page with that submission open
    expect(await screen.findByText(/She has finished her homework/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Duyệt điểm' })).toBeInTheDocument()
  })

  it('is empty-state friendly', async () => {
    base({ 'GET /grading': { items: [], limit: 100, counts: { pending: 0, proposed: 0, approved: 0, rejected: 0, skipped: 0, failed: 0, waiting: 0 } } })
    renderApp(PAGE)
    await userEvent.click(await screen.findByRole('tab', { name: /Học sinh/ }))
    expect(await screen.findByText(/Không có bài nào chờ duyệt/)).toBeInTheDocument()
  })
})

const DRAFTS: AssignmentList = { sources: [{ id: 'c1', label: 'Tiếng Anh A1' }], items: [
  { id: 'd1', class_id: 'c1', course: 'Tiếng Anh A1', title: 'Viết 5 câu về em', description: 'Viết 5 câu về bản thân em dùng thì hiện tại hoàn thành.', max_points: 10, origin: 'ai', status: 'draft', posting: 'draft', topic: null, scheduled: null, assignees: null, due: null, publish: false, error: null,
    criteria: [{ id: 'thi', label: 'Đúng thì', points: 6, descriptor: '' }, { id: 'so_cau', label: 'Đủ 5 câu', points: 4, descriptor: '' }], answer_key: null, language: 'en', materials: [{ kind: 'drive', id: 'f1', title: 'Phiếu bài tập', share: 'STUDENT_COPY' }], created_by: 'staff:nv1', created_at: '2026-10-22T02:00:00Z' }] }
const CLASS_G = { id: 'c1', name: 'Tiếng Anh A1', sandbox_id: 'sb2', sandbox: 'Tổng kết', grader_sandbox_id: 'sb1', account: 'Cô Lan', account_id: 'g1', linked: true, active: true, since: '2026-10-20T02:00:00Z', folder: 'x', folder_url: null,
  owned: false, can_upload: false, webhook: null, has_webhook: false, lessons: { done: 0, failed: 0, waiting: 0, held: 0 }, classroom: { course_id: '111', course: 'Tiếng Anh A1', account_id: 'g1' },
  policy: { recap_mode: 'review' as const, grading_mode: 'review' as const, assignment_post_mode: 'manual' as const }, can_grade: true, grading: { assignments: 2, to_review: 0, pending: 0, waiting: 0, done: 0 } }
const TAB = '/classes/c1?tab=assignments'
const OPTIONS = { topics: [{ id: 't1', name: 'Tuần 1' }], students: [{ id: 'u1', name: 'Nguyễn Minh An' }, { id: 'u2', name: 'Trần Bảo Châu' }], problems: {} }
const tab = (extra: Record<string, unknown> = {}, session = CLASS_STAFF) => server({ 'GET /session': session, 'GET /classes': { items: [CLASS_G] }, 'GET /lessons?class_id=c1': { items: [], limit: 100, can_upload: false, max_mb: 1, classes: [] },
  'GET /classes/c1/assignments': { class: { id: 'c1', name: 'Tiếng Anh A1', grading_mode: 'review' }, items: [{ id: 'd1', title: 'Viết 5 câu về em', state: 'draft', ours: true, posting: 'draft', topic: null, scheduled: null, assignees: null, gradable: true, max_points: 10, due: null, created_at: '2026-10-22T02:00:00Z', submissions: 0,
    counts: { pending: 0, proposed: 0, approved: 0, rejected: 0, skipped: 0, failed: 0, waiting: 0 } }] },
  'GET /assignments': DRAFTS, 'GET /classes/c1/classroom-options': OPTIONS, 'GET /class-kinds': { items: [] }, 'GET /google/picker': { configured: true, default_account_id: 'g1', browse: true, accounts: [{ id: 'g1', label: 'Cô Lan', email: 'co.lan@truong.vn', can_pick: true }] }, 'POST /google/picker/token': { token: 't', expires_in: 3599, api_key: 'k', app_id: '1', email: null }, ...extra })

describe('Bài tập của lớp', () => {
  it('shows a draft with its guide and says nothing exists in Classroom until it is approved', async () => {
    tab()
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Viết 5 câu về em'))
    expect(await screen.findByText(/Chưa có gì trên Classroom/)).toBeInTheDocument()
    expect(screen.getByText(/Đúng thì: 6 điểm/)).toBeInTheDocument()
    expect(screen.getByText('Bài nói: tiếng Anh')).toBeInTheDocument()
    expect(screen.getByText('Phiếu bài tập')).toBeInTheDocument()  // what will be attached
    expect(screen.getByText(/Mỗi học sinh một bản sao/)).toBeInTheDocument()
    expect(screen.getAllByText('AI soạn').length).toBeGreaterThan(0)
  })

  it('approving sends the choice to publish and the due date', async () => {
    const s = tab({ 'POST /assignments/d1/decision': { status: 'created', coursework_id: 'w9', published: true } })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Viết 5 câu về em'))
    await userEvent.click(await screen.findByRole('radio', { name: /Đăng ngay cho học sinh/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Duyệt và tạo trên Classroom' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'POST')).toBe(true))
    expect(s.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ action: 'approve', publish: true })
  })

  it('a new assignment cannot be saved until its criteria add up to the total', async () => {
    tab({}, OWNER)
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }))
    await userEvent.type(await screen.findByLabelText('Tiêu đề'), 'Bài mới')
    await userEvent.type(screen.getByLabelText('Đề bài'), 'Làm bài tập trang 45 và nộp trên Classroom.')
    await userEvent.type(screen.getByLabelText('Tiêu chí 1'), 'Đúng')
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '4')
    expect(screen.getByText(/phải bằng tổng điểm/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeDisabled()
    await userEvent.clear(screen.getByLabelText('Điểm tiêu chí 1'))
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '10')
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeEnabled()
  })

  it('sends the attached files with a new assignment, for this class', async () => {
    const s = tab({ 'POST /assignments': { ...DRAFTS.items[0], id: 'd2' } }, OWNER)
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }))
    await userEvent.type(await screen.findByLabelText('Tiêu đề'), 'Bài mới')
    await userEvent.type(screen.getByLabelText('Đề bài'), 'Làm phiếu bài tập đính kèm và nộp trên Classroom.')
    await userEvent.type(screen.getByLabelText('Tiêu chí 1'), 'Đúng')
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '10')
    picker.open.mockImplementation(async (_cfg: unknown, onPick: (f: unknown[]) => void) => onPick([{ url: 'https://drive.google.com/file/d/abc123/view', title: 'Phiếu bài tập.pdf', share: 'VIEW' }]))
    await userEvent.click(screen.getByRole('button', { name: /Chọn từ Google Drive/ }))
    await screen.findByText('Phiếu bài tập.pdf')
    await userEvent.selectOptions(screen.getByLabelText('Quyền của học sinh với tệp 1'), 'STUDENT_COPY')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'POST' && c.path === '/assignments')).toBe(true))
    expect(s.calls.find((c) => c.method === 'POST' && c.path === '/assignments')!.body).toMatchObject({ class_id: 'c1', materials: [{ url: 'https://drive.google.com/file/d/abc123/view', share: 'STUDENT_COPY' }] })
  })

  it('sends the answer key and the teacher\'s own way of checking with a new assignment', async () => {
    const s = tab({ 'POST /assignments': { ...DRAFTS.items[0], id: 'd3' } }, OWNER)
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }))
    await userEvent.type(await screen.findByLabelText('Tiêu đề'), 'Chép chính tả')
    await userEvent.type(screen.getByLabelText('Đề bài'), 'Nghe và chép lại bài nghe, chụp ảnh nộp lên Classroom.')
    await userEvent.type(screen.getByLabelText('Tiêu chí 1'), 'Chép đúng')
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '10')
    await userEvent.type(screen.getByLabelText('Đáp án'), 'Did you see the email about the sales meeting?')
    await userEvent.type(screen.getByLabelText('Cách kiểm tra'), 'Phải đủ các câu, đúng từng từ, bỏ qua dấu câu.')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'POST' && c.path === '/assignments')).toBe(true))
    expect(s.calls.find((c) => c.method === 'POST' && c.path === '/assignments')!.body).toMatchObject({
      answer_key: 'Did you see the email about the sales meeting?', check_prompt: 'Phải đủ các câu, đúng từng từ, bỏ qua dấu câu.' })
  })

  const NO_COURSE = { ...CLASS_G, can_grade: false, grader_sandbox_id: null }
  it('asks staff to have the owner connect a course when the class has none', async () => {
    tab({ 'GET /classes': { items: [NO_COURSE] } })
    renderApp(TAB)
    expect(await screen.findByText(/Nhờ chủ trung tâm nối/)).toBeInTheDocument()
  })

  it('lets the owner connect a Classroom course right there when the class has none', async () => {
    const s = tab({ 'GET /classes': { items: [NO_COURSE] },
      'GET /google/accounts': { configured: true, sources: [], kinds: [], sandboxes: [{ id: 'sb1', title: 'Chấm bài', purpose: 'classroom_grader' }],
        items: [{ id: 'g1', label: 'Google của cô Lan', email: null, status: 'active', can: { classroom: true, classroom_post: false, drive: false, drive_read: false }, connected_at: new Date().toISOString(), connected_by: 'x', used_by: [], refs: [] }] },
      'GET /google/accounts/g1/courses': { items: [{ id: '111', name: 'Tiếng Anh 6A', section: '', connected: false }] }, 'POST /google/classroom-sources': { id: 's1', course_id: '111', account: 'x' } }, OWNER)
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: 'Nối khoá học này' }))
    await waitFor(() => expect(s.posted('/google/classroom-sources')[0].body).toEqual({ sandbox_id: 'sb1', account_id: 'g1', course_id: '111', label: 'Tiếng Anh 6A' }))
  })

  // --- posting the way Classroom does ---
  const MADE = (over: Record<string, unknown> = {}) => ({ class: { id: 'c1', name: 'Tiếng Anh A1', grading_mode: 'review' }, items: [
    { id: 'm1', title: 'Bài đã tạo', state: 'created', ours: true, posting: 'classroom_draft', topic: null, scheduled: null, assignees: null, gradable: true, max_points: 10, due: null,
      created_at: '2026-10-22T02:00:00Z', submissions: 0, description: 'Viết năm câu về kỳ nghỉ của em.', criteria: [{ id: 'thi', label: 'Đúng thì', points: 10, descriptor: '' }], materials: [], answer_key: null,
      check_prompt: null, language: null, counts: { pending: 0, proposed: 0, approved: 0, rejected: 0, skipped: 0, failed: 0, waiting: 0 }, ...over }] })
  const made = (over: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => tab({ 'GET /classes/c1/assignments': MADE(over), 'GET /assignments': { sources: DRAFTS.sources, items: [] }, ...extra })

  it('sends the schedule, topic and chosen students with a new assignment', async () => {
    const s = tab({ 'POST /assignments': { ...DRAFTS.items[0], id: 'd2' } }, OWNER)
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }))
    await userEvent.type(await screen.findByLabelText('Tiêu đề'), 'Bài mới')
    await userEvent.type(screen.getByLabelText('Đề bài'), 'Làm bài tập trang 45 và nộp trên Classroom.')
    await userEvent.type(screen.getByLabelText('Tiêu chí 1'), 'Đúng')
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '10')
    await userEvent.click(screen.getByRole('radio', { name: /Hẹn giờ/ }))
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeDisabled()  // a schedule needs its time
    await userEvent.type(screen.getByLabelText('Giờ đăng'), '2030-01-05T08:00')
    await userEvent.type(screen.getByLabelText('Chủ đề trong Classroom'), 'Tuần 1')
    await userEvent.click(screen.getByRole('radio', { name: 'Chỉ một số học sinh' }))
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeDisabled()  // some students, but none picked
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Trần Bảo Châu' }))
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    await waitFor(() => expect(s.posted('/assignments').length).toBe(1))
    const body = s.posted('/assignments')[0].body as Record<string, unknown>
    expect(body).toMatchObject({ topic_name: 'Tuần 1', assignees: [{ id: 'u2', name: 'Trần Bảo Châu' }], publish: true })
    expect(String(body.scheduled)).toMatch(/^2030-01-05T/)
  })

  it('shows where work stands in Classroom and shows a Classroom draft to the students on request', async () => {
    const s = made({}, { 'POST /assignments/m1/publish': { status: 'published' } })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    expect((await screen.findAllByText(/Bản nháp trong Classroom \(học sinh chưa thấy\)/)).length).toBeGreaterThan(0)
    await userEvent.click(screen.getByRole('button', { name: 'Đăng cho học sinh ngay' }))
    await waitFor(() => expect(s.posted('/assignments/m1/publish').length).toBe(1))
  })

  it('does not offer to publish work that is already out', async () => {
    made({ posting: 'published' })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    expect(await screen.findByRole('button', { name: 'Sửa' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Đăng cho học sinh ngay' })).toBeNull()
  })

  it('edits work in Classroom and sends only what the form holds, including the cleared due date', async () => {
    const s = made({ due: '2030-02-01T03:00:00Z' }, { 'PATCH /assignments/m1': { status: 'updated' } })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    await userEvent.clear(await screen.findByLabelText('Tiêu đề'))
    await userEvent.type(screen.getByLabelText('Tiêu đề'), 'Tên khác')
    await userEvent.clear(screen.getByLabelText('Hạn nộp'))
    await userEvent.click(screen.getByRole('button', { name: 'Lưu thay đổi' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'PATCH')).toBe(true))
    expect(s.calls.find((c) => c.method === 'PATCH')!.body).toMatchObject({ title: 'Tên khác', due: null, max_points: 10 })
  })

  it('will not save an edit whose criteria no longer add up to the points', async () => {
    made()
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    await userEvent.clear(await screen.findByLabelText('Tổng điểm'))
    await userEvent.type(screen.getByLabelText('Tổng điểm'), '20')
    expect(screen.getByRole('button', { name: 'Lưu thay đổi' })).toBeDisabled()
    expect(screen.getByText(/phải bằng tổng điểm/)).toBeInTheDocument()
  })

  it('asks before taking the work out of Classroom, and only then deletes it', async () => {
    const s = made({}, { 'DELETE /assignments/m1': { status: 'deleted' } })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    await userEvent.click(await screen.findByRole('button', { name: 'Xoá khỏi Classroom' }))
    expect(screen.getByText(/Bài nộp của học sinh trên Classroom cũng mất/)).toBeInTheDocument()
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Không xoá' }))
    expect(s.calls.some((c) => c.method === 'DELETE')).toBe(false)
    await userEvent.click(screen.getByRole('button', { name: 'Xoá khỏi Classroom' }))
    await userEvent.click(screen.getByRole('button', { name: 'Xác nhận xoá' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'DELETE' && c.path === '/assignments/m1')).toBe(true))
  })

  it('does not offer to manage work a teacher made by hand in Classroom', async () => {
    made({ ours: false, posting: 'classroom' })
    renderApp(TAB)
    await userEvent.click(await screen.findByText('Bài đã tạo'))
    expect(await screen.findByText('Viết năm câu về kỳ nghỉ của em.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Xoá khỏi Classroom' })).toBeNull()
  })
})
