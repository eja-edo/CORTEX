import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { OWNER, fail, renderApp, server } from '../test/harness'

const OPTIONS = {
  templates: [{ id: 'khach_im', label: 'Hỏi lại khách im' }, { id: 'dung_hen', label: 'Nhắc đúng hẹn' }], intents: [{ id: 'hoi_gia', label: 'Hỏi giá' }], has_sandbox: true,
  locked: ['Tự gửi tin cho khách (chỉ soạn nháp)', 'Đặt lịch, gửi phiếu đăng ký'], always: 'Mọi số, ngày, giờ trong nháp phải khớp catalog.',
}
const SUMMARY = { trigger: 'Khách im 20 giờ', tools: ['Đọc tin nhắn gần nhất (đã che tên, SĐT)', 'Soạn nháp cho nhân viên duyệt'], locked: [], always: '', never_say_count: 26, must_handoff: [] }

const fill = async () => {
  await userEvent.type(await screen.findByPlaceholderText('nhac-gia'), 'nhac-gia')
  await userEvent.type(screen.getByPlaceholderText(/Hỏi lại khách đã hỏi giá/), 'Hỏi lại khách đã hỏi giá rồi im quá nửa ngày')
  await userEvent.type(screen.getByLabelText(/Cách làm của doanh nghiệp/), 'Nhắc nhẹ, nêu đúng một lợi ích của khoá, không thúc ép chốt.')
}

describe('Tạo kỹ năng', () => {
  it('shows what is always locked before the person types anything, and keeps Save off until the form is valid', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS })
    renderApp('/skills/new')
    expect(await screen.findByText('Tự gửi tin cho khách (chỉ soạn nháp)')).toBeInTheDocument()
    expect(screen.getByText(/Mọi số, ngày, giờ trong nháp phải khớp catalog/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeDisabled()
    expect(screen.getByText('Điền tên, mô tả và cách làm để xem.')).toBeInTheDocument()
  })

  it('shows the server\'s own reading of the form once it is valid, then saves the draft', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS, 'POST /skills/preview': { errors: [], summary: SUMMARY }, 'POST /skills': { id: 's9' }, 'GET /skills': { items: [], counts: { all: 0, live: 0, shadow: 0, draft: 0, retired: 0 }, min_trial_runs: 10 } })
    renderApp('/skills/new')
    await fill()
    expect(await screen.findByText('Khách im 20 giờ', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('Soạn nháp cho nhân viên duyệt')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    await waitFor(() => expect(s.posted('/skills')).toHaveLength(1))
    const sent = s.posted('/skills')[0].body as Record<string, unknown>
    expect(sent).toMatchObject({ template: 'khach_im', slug: 'nhac-gia', after_hours: 20, intent: null, max_touches: 2, never_say: [], must_handoff: [] })
    expect(Object.keys(sent)).not.toContain('requires_tools') // the form has no way to ask for more power
    expect(s.posted('/skills')[0].csrf).toBe('csrf-token-1')
  })

  it('adds and removes phrases as chips and sends them', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS, 'POST /skills/preview': { errors: [], summary: SUMMARY }, 'POST /skills': { id: 's9' }, 'GET /skills': { items: [], counts: { all: 0, live: 0, shadow: 0, draft: 0, retired: 0 }, min_trial_runs: 10 } })
    renderApp('/skills/new')
    await fill()
    const never = screen.getByLabelText('Cụm không được nói thêm')
    await userEvent.type(never, 'giá sốc{Enter}chốt ngay{Enter}')
    await userEvent.click(screen.getByRole('button', { name: 'Bỏ chốt ngay' }))
    await screen.findByText('Khách im 20 giờ', {}, { timeout: 3000 })
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    await waitFor(() => expect(s.posted('/skills')).toHaveLength(1))
    expect((s.posted('/skills')[0].body as { never_say: string[] }).never_say).toEqual(['giá sốc'])
  })

  it('blocks saving and shows the lint error when the server says the form cannot work', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS, 'POST /skills/preview': { errors: ['match intent \'x\' is not in the domain pack'], summary: SUMMARY } })
    renderApp('/skills/new')
    await fill()
    expect(await screen.findByText(/is not in the domain pack/, {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Lưu bản nháp' })).toBeDisabled()
    expect(s.posted('/skills')).toHaveLength(0)
  })

  it('reports a refusal on save without leaving the page', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS, 'POST /skills/preview': { errors: [], summary: SUMMARY }, 'POST /skills': fail(422, { errors: ['tools not allowed'] }) })
    renderApp('/skills/new')
    await fill()
    await screen.findByText('Khách im 20 giờ', {}, { timeout: 3000 })
    await userEvent.click(screen.getByRole('button', { name: 'Lưu bản nháp' }))
    expect(await screen.findByText('tools not allowed')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Tạo kỹ năng từ mẫu' })).toBeInTheDocument()
  })

  it('hides the follow-up fields for the "remind on the promised day" template', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/form-options': OPTIONS })
    renderApp('/skills/new')
    expect(await screen.findByLabelText(/Hỏi lại sau khi khách im/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('radio', { name: 'Nhắc đúng hẹn' }))
    expect(screen.queryByLabelText(/Hỏi lại sau khi khách im/)).toBeNull()
  })

  it('tells the owner to create a sandbox first when there is none', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/form-options': { ...OPTIONS, has_sandbox: false } })
    renderApp('/skills/new')
    expect(await screen.findByText(/chưa có sandbox chăm sóc khách/)).toBeInTheDocument()
  })
})
