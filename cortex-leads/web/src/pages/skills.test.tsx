import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { SHADOW, SKILLS } from '../test/fixtures'
import { OWNER, STAFF, fail, renderApp, server } from '../test/harness'

const base = (me = OWNER, extra: Record<string, unknown> = {}) => server({ 'GET /session': me, 'GET /skills': SKILLS, 'GET /skills/s2': SHADOW, ...extra })

describe('Kỹ năng', () => {
  it('lists skills with plain triggers and status, and filters by tab', async () => {
    base()
    renderApp('/skills')
    const rows = await screen.findAllByRole('row', { selected: false })
    expect(rows.length).toBeGreaterThan(2)
    expect(screen.getByText('tra-loi-khach')).toBeInTheDocument()
    expect(screen.getByText('Đang chạy thử 7/10')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Đang chạy thử/ }))
    expect(screen.queryByText('tra-loi-khach')).toBeNull()
    expect(screen.getByText('tuy-chinh-nhac-gia')).toBeInTheDocument()
  })

  it('shows the trial: progress, what was drafted, what the safety net blocked, and why Bật is not yet possible', async () => {
    base()
    renderApp('/skills')
    await userEvent.click(await screen.findByText('tuy-chinh-nhac-gia'))
    expect(await screen.findByText('7 / 10')).toBeInTheDocument()
    expect(screen.getByText(/Cần thêm 3 lượt thử/)).toBeInTheDocument()
    expect(screen.getByText(/Chị ơi lớp IELTS còn chỗ ạ/)).toBeInTheDocument()
    expect(screen.getByText('Bị bộ kiểm chặn')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Bật \(cần đủ 10 lượt\)/ })).toBeDisabled()
    expect(screen.getByText('Chỉ soạn nháp cho nhân viên duyệt.', { exact: false })).toBeInTheDocument()
  })

  it('lets the owner go live once the trial is long enough, and reports the server rule if it still refuses', async () => {
    const ready = { ...SHADOW, runs: 10, ready: true, can: { ...SHADOW.can, live: true } }
    const s = base(OWNER, { 'GET /skills/s2': ready, 'POST /skills/s2/live': fail(409, { code: 'SKILL_RULE', message: 'needs 10 trial runs before going live, has 9' }) })
    renderApp('/skills')
    await userEvent.click(await screen.findByText('tuy-chinh-nhac-gia'))
    await userEvent.click(await screen.findByRole('button', { name: 'Bật' }))
    await waitFor(() => expect(s.posted('/skills/s2/live')).toHaveLength(1))
    expect(await screen.findByText(/needs 10 trial runs/)).toBeInTheDocument()
  })

  it('starts a trial for a draft and can switch a trial off', async () => {
    const s = base(OWNER, { 'GET /skills/s3': { ...SHADOW, id: 's3', name: 'tuy-chinh-hoc-bong', status: 'draft', runs: 0, trial_drafts: [], can: { trial: true, live: false, off: false, again: false } },
      'POST /skills/s3/trial': { status: 'shadow' } })
    renderApp('/skills')
    await userEvent.click(await screen.findByText('tuy-chinh-hoc-bong'))
    await userEvent.click(await screen.findByRole('button', { name: 'Chạy thử' }))
    await waitFor(() => expect(s.posted('/skills/s3/trial')).toHaveLength(1))
    expect(s.posted('/skills/s3/trial')[0].csrf).toBe('csrf-token-1')
  })

  it('shows staff the same list but no way to change a skill', async () => {
    base(STAFF)
    renderApp('/skills')
    await userEvent.click(await screen.findByText('tuy-chinh-nhac-gia'))
    expect(await screen.findByText('Chỉ chủ mới đổi được trạng thái kỹ năng.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tắt kỹ năng' })).toBeNull()
  })

  it('has an empty and an error state', async () => {
    server({ 'GET /session': OWNER, 'GET /skills': fail(500, 'x') })
    renderApp('/skills')
    expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được dữ liệu')
  })
})
