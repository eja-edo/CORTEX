import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AssignmentTemplate } from '../api/types'
import { OWNER, CLASS_STAFF, renderApp, server } from '../test/harness'

afterEach(() => vi.unstubAllGlobals())

const T = (o: Partial<AssignmentTemplate> = {}): AssignmentTemplate => ({ id: 't1', kind_id: 'k1', name: 'Viết đoạn văn', title: 'Viết đoạn văn về gia đình', description: 'Viết một đoạn văn 8 câu về gia đình em.', max_points: 10,
  criteria: [{ id: 'y0', label: 'Ý chính', points: 6, descriptor: '' }, { id: 't1', label: 'Trình bày', points: 4, descriptor: '' }], answer_key: 'Bài mẫu', check_prompt: 'Bỏ qua dấu câu', language: 'vi', topic_name: 'Tuần 1',
  materials: [{ url: 'https://drive.google.com/file/d/abc123/view', title: 'Phiếu', share: 'STUDENT_COPY' }], created_by: 'staff:owner', created_at: '2026-11-04T02:00:00Z', ...o })
const CLASS_G = { id: 'c1', name: 'Tiếng Anh A1', sandbox_id: null, sandbox: '', grader_sandbox_id: 'sb1', account: 'Cô Lan', account_id: 'g1', linked: true, active: true, since: '2026-10-20T02:00:00Z', folder: 'x', folder_url: null,
  owned: false, can_upload: false, webhook: null, has_webhook: false, lessons: { done: 0, failed: 0, waiting: 0, held: 0 }, classroom: { course_id: 'x', course: 'A1', account_id: 'g1' },
  policy: { recap_mode: 'review' as const, grading_mode: 'review' as const, assignment_post_mode: 'manual' as const }, can_grade: true, grading: { assignments: 0, to_review: 0, pending: 0, waiting: 0, done: 0 } }
const TAB = '/classes/c1?tab=assignments'
const ONLY = { id: 't2', name: 'Chỉ đề', title: null, description: 'Đề không có thang điểm, chỉ có chữ.', max_points: null, criteria: [], answer_key: null, check_prompt: null, language: null, topic_name: null, materials: [] }
const compose = (kinds: unknown, extra: Record<string, unknown> = {}) => server({ 'GET /session': CLASS_STAFF, 'GET /classes': { items: [CLASS_G] }, 'GET /lessons?class_id=c1': { items: [], limit: 100, can_upload: false, max_mb: 1, classes: [] },
  'GET /classes/c1/assignments': { class: { id: 'c1', name: 'Tiếng Anh A1', grading_mode: 'review' }, items: [] }, 'GET /assignments': { items: [], sources: [{ id: 'c1', label: 'Tiếng Anh A1' }] },
  'GET /classes/c1/classroom-options': { topics: [], students: [], problems: {} }, 'GET /class-kinds': kinds, 'GET /google/picker': { configured: false, default_account_id: null, browse: true, accounts: [] }, ...extra })
const KINDS = { items: [{ id: 'k1', name: 'IELTS', templates: 2 }, { id: 'k2', name: 'Thiếu nhi', templates: 1 }] }

describe('Bài tập mẫu', () => {
  it('picks the kind of class first, then the template, and fills the form with it', async () => {
    compose(KINDS, { 'GET /class-kinds/k1/templates': { kind: { id: 'k1', name: 'IELTS' }, items: [T(), T(ONLY)] },
      'GET /class-kinds/k2/templates': { kind: { id: 'k2', name: 'Thiếu nhi' }, items: [T({ id: 't3', kind_id: 'k2', name: 'Tô màu', title: 'Tô màu con vật', max_points: 5, criteria: [{ id: 'a0', label: 'Tô đủ', points: 5, descriptor: '' }] })] } })
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }, { timeout: 5000 }))
    await userEvent.type(await screen.findByLabelText('Tiêu đề'), 'Tự gõ')
    await userEvent.click(await screen.findByRole('button', { name: /Chọn bài tập mẫu/ }))
    expect(await screen.findByRole('radio', { name: 'IELTS' })).toBeChecked()  // the first kind that has templates
    await userEvent.click(within_list('Chỉ đề'))
    expect(screen.getByLabelText('Đề bài')).toHaveValue('Đề không có thang điểm, chỉ có chữ.')
    expect(screen.getByLabelText('Tiêu đề')).toHaveValue('Tự gõ')  // the template has no title: what was typed stays
    expect(screen.getByLabelText('Tổng điểm')).toHaveValue('10')
    expect(screen.getByText(/Đã điền từ «Chỉ đề» \(IELTS\)/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Chọn bài tập mẫu/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'Thiếu nhi' }))
    await userEvent.click(await screen.findByRole('button', { name: /^Tô màu/ }))
    expect(screen.getByLabelText('Tiêu đề')).toHaveValue('Tô màu con vật')
    expect(screen.getByLabelText('Tổng điểm')).toHaveValue('5')
    expect(screen.getByLabelText('Tiêu chí 1')).toHaveValue('Tô đủ')
    await userEvent.click(screen.getByRole('button', { name: /Chọn bài tập mẫu/ }))
    await userEvent.click(screen.getByRole('radio', { name: 'IELTS' }))
    await userEvent.click(await screen.findByRole('button', { name: /^Viết đoạn văn/ }))
    expect(screen.getByLabelText('Tiêu đề')).toHaveValue('Viết đoạn văn về gia đình')
    expect(screen.getByLabelText('Tiêu chí 2')).toHaveValue('Trình bày')
    expect(screen.getByLabelText('Điểm tiêu chí 1')).toHaveValue('6')
    expect(screen.getByLabelText('Đáp án')).toHaveValue('Bài mẫu')
    expect(screen.getByLabelText('Cách kiểm tra')).toHaveValue('Bỏ qua dấu câu')
    expect(screen.getByLabelText('Ngôn ngữ bài nói')).toHaveValue('vi')
    expect(screen.getByLabelText('Chủ đề trong Classroom')).toHaveValue('Tuần 1')
    expect(screen.getByText('Phiếu')).toBeInTheDocument()  // the attachment's name; its address is not shown
    expect(screen.queryByLabelText('Địa chỉ tệp 1')).toBeNull()
    expect(screen.getByLabelText('Quyền của học sinh với tệp 1')).toHaveValue('STUDENT_COPY')
  })

  it('says why there is nothing to pick when no kind has a template, and links to where to make one', async () => {
    compose({ items: [{ id: 'k1', name: 'IELTS', templates: 0 }] })
    renderApp(TAB)
    await userEvent.click(await screen.findByRole('button', { name: /Soạn bài tập/ }, { timeout: 5000 }))
    expect(await screen.findByText(/Chưa có bài tập mẫu nào/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Chọn bài tập mẫu/ })).toBeDisabled()
  })

  it('has no kind to choose on the class page: a class is not tied to a kind', async () => {
    compose(KINDS)
    renderApp(TAB)
    await screen.findByRole('button', { name: /Soạn bài tập/ })
    expect(screen.queryByLabelText('Loại lớp')).toBeNull()
  })

  it('saves a template of a kind with the form\'s fields, and refuses a rubric that does not add up before sending', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /class-kinds': { items: [{ id: 'k1', name: 'IELTS', templates: 0 }] },
      'GET /class-kinds/k1/templates': { kind: { id: 'k1', name: 'IELTS' }, items: [] }, 'POST /class-kinds/k1/templates': T() })
    renderApp('/templates')
    await userEvent.click(await screen.findByRole('button', { name: /Thêm bài tập mẫu/ }))
    await userEvent.type(screen.getByLabelText('Tên bài tập mẫu'), 'Writing task 1')
    await userEvent.type(screen.getByLabelText('Tổng điểm'), '10')
    await userEvent.type(screen.getByLabelText('Tiêu chí 1'), 'Ý chính')
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '4')
    expect(screen.getByRole('button', { name: 'Lưu bài tập mẫu' })).toBeDisabled()  // 4 of 10
    await userEvent.clear(screen.getByLabelText('Điểm tiêu chí 1'))
    await userEvent.type(screen.getByLabelText('Điểm tiêu chí 1'), '10')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bài tập mẫu' }))
    await waitFor(() => expect(s.posted('/class-kinds/k1/templates')).toHaveLength(1))
    expect(s.posted('/class-kinds/k1/templates')[0].body).toMatchObject({ name: 'Writing task 1', max_points: 10, title: null, criteria: [{ label: 'Ý chính', points: 10 }], materials: [] })
  })
})

const within_list = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) })
