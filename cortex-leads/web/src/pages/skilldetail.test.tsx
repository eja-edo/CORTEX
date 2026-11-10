import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { SkillDetail } from '../api/types'
import { SHADOW, SKILLS } from '../test/fixtures'
import { OWNER, STAFF, renderApp, server } from '../test/harness'

const FORM = { template: 'khach_im' as const, slug: 'nhac-gia', description: 'Hỏi lại khách đã hỏi giá rồi im quá nửa ngày', instructions: 'Nhắc nhẹ, nêu đúng một lợi ích của khoá khách quan tâm.',
  after_hours: 4, intent: 'hoi_gia', max_touches: 1, never_say: ['chốt ngay hôm nay'], must_handoff: ['bảo hành'] }
const DETAIL: SkillDetail = { ...SHADOW, id: 's2', status: 'draft', runs: 0, form: FORM, never_say_count: 27, limits: { min_gap: '24h', expires_after: '14d' },
  history: [{ id: 'e2', at: new Date().toISOString(), actor: 'staff:owner', summary: 'Sửa kỹ năng «tuy-chinh-nhac-gia»', restorable: true,
    changes: [{ field: 'max_touches', before: 2, after: 1 }] }, { id: 'e1', at: '2026-10-18T02:05:00Z', actor: 'staff:owner', summary: 'Tạo kỹ năng «tuy-chinh-nhac-gia»', restorable: false, changes: [] }] }
const OPTIONS = { templates: [{ id: 'khach_im', label: 'Hỏi lại khách im' }, { id: 'dung_hen', label: 'Nhắc đúng hẹn' }], intents: [{ id: 'hoi_gia', label: 'Hỏi giá' }], has_sandbox: true, locked: ['Tự gửi tin cho khách'], always: 'Luật chung.' }

describe('Chi tiết kỹ năng', () => {
  it('shows what the person wrote, the limits, the sandbox and where to edit', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/s2': DETAIL })
    renderApp('/skills/s2')
    expect(await screen.findByRole('heading', { name: 'Kỹ năng riêng: nhac-gia' })).toBeInTheDocument()
    expect(screen.getByText(/Nhắc nhẹ, nêu đúng một lợi ích/)).toBeInTheDocument()
    expect(screen.getByText('1 lần mỗi khách')).toBeInTheDocument()
    expect(screen.getByText('24 giờ')).toBeInTheDocument()
    expect(screen.getByText('chốt ngay hôm nay')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Chăm sóc khách' })).toHaveAttribute("href", "/settings?tab=ai")
    expect(screen.getByRole('link', { name: /Sửa/ })).toHaveAttribute('href', '/skills/s2/edit')
  })

  it('lists each change field by field and puts one back after a confirmation', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/s2': DETAIL, 'POST /skills/s2/revert': { id: 's2' } })
    renderApp('/skills/s2')
    await userEvent.click(await screen.findByRole('tab', { name: /Lịch sử chỉnh sửa/ }))
    expect(await screen.findByText(/Nhắn tối đa:/)).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Khôi phục' })).toHaveLength(1) // the creation line has nothing to go back to
    await userEvent.click(screen.getByRole('button', { name: 'Khôi phục' }))
    await userEvent.click(within(screen.getByText(/Đưa nội dung về như trước/).parentElement!).getByRole('button', { name: 'Khôi phục' }))
    await waitFor(() => expect(s.posted('/skills/s2/revert')).toHaveLength(1))
    expect(s.posted('/skills/s2/revert')[0].body).toEqual({ event_id: 'e2' })
  })

  it('asks before deleting, then says it is only hidden', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/s2': DETAIL, 'POST /skills/s2/delete': { status: 'retired' } })
    renderApp('/skills/s2')
    await userEvent.click(await screen.findByRole('button', { name: /Xoá \(khoá\) kỹ năng/ }))
    expect(s.posted('/skills/s2/delete')).toHaveLength(0)
    await userEvent.click(screen.getByRole('button', { name: 'Xoá kỹ năng' }))
    await waitFor(() => expect(s.posted('/skills/s2/delete')).toHaveLength(1))
  })

  it('shows a deleted skill with who deleted it and a way back', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/s2': { ...DETAIL, deleted: true, deleted_by: 'staff:owner', deleted_at: new Date().toISOString(), status: 'retired',
      can: { ...DETAIL.can, edit: false, delete: false, restore: true } }, 'POST /skills/s2/restore': { status: 'retired' } })
    renderApp('/skills/s2')
    expect(await screen.findByText(/Kỹ năng đã bị xoá bởi staff:owner/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /Sửa/ })).toBeNull()
    await userEvent.click(screen.getByRole('button', { name: 'Khôi phục' }))
    await waitFor(() => expect(s.posted('/skills/s2/restore')).toHaveLength(1))
  })

  it('shows staff the content but not the history, and no delete', async () => {
    server({ 'GET /session': STAFF, 'GET /skills/s2': { ...DETAIL, history: [] } })
    renderApp('/skills/s2')
    await screen.findByRole('heading', { name: 'Kỹ năng riêng: nhac-gia' })
    expect(screen.queryByRole('button', { name: /Xoá \(khoá\)/ })).toBeNull()
    await userEvent.click(screen.getByRole('tab', { name: /Lịch sử chỉnh sửa/ }))
    expect(screen.getByText('Chỉ chủ xem được lịch sử chỉnh sửa.')).toBeInTheDocument()
  })
})

describe('Sửa kỹ năng', () => {
  it('opens with the form as it was filled, the name fixed, and saves in place', async () => {
    const s = server({ 'GET /session': OWNER, 'GET /skills/s2': { ...DETAIL, status: 'live' }, 'GET /skills/form-options': OPTIONS,
      'POST /skills/preview': { errors: [], summary: { trigger: 'Khách im 4 giờ', tools: ['Soạn nháp'], locked: [], always: '', never_say_count: 27, must_handoff: [] } }, 'PUT /skills/s2': { id: 's2' } })
    renderApp('/skills/s2/edit')
    const slug = await screen.findByPlaceholderText('nhac-gia')
    expect(slug).toHaveValue('nhac-gia')
    expect(slug).toBeDisabled()
    expect(screen.getByText(/Lưu sẽ áp dụng ngay/)).toBeInTheDocument()
    const how = screen.getByLabelText(/Cách làm của doanh nghiệp/)
    await userEvent.clear(how)
    await userEvent.type(how, 'Nhắc nhẹ và nêu đúng một lợi ích, không thúc ép chốt.')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng ngay' }))
    await waitFor(() => expect(s.calls.some((c) => c.method === 'PUT' && c.path === '/skills/s2')).toBe(true))
    const put = s.calls.find((c) => c.method === 'PUT')!
    expect(put.body).toMatchObject({ slug: 'nhac-gia', after_hours: 4, never_say: ['chốt ngay hôm nay'], instructions: 'Nhắc nhẹ và nêu đúng một lợi ích, không thúc ép chốt.' })
    expect(put.csrf).toBe('csrf-token-1')
  })

  it('refuses a skill that has no stored form', async () => {
    server({ 'GET /session': OWNER, 'GET /skills/s1': { ...DETAIL, id: 's1', form: null, can: { ...DETAIL.can, edit: false } } })
    renderApp('/skills/s1/edit')
    expect(await screen.findByText(/không sửa được ở đây/)).toBeInTheDocument()
  })
})

describe('Danh sách có tab Đã xoá', () => {
  it('keeps deleted skills out of the other tabs', async () => {
    const gone = { ...SKILLS.items[2], id: 's9', name: 'tuy-chinh-cu', deleted: true, status: 'retired' as const, can: { ...SKILLS.items[2].can, restore: true, edit: false, delete: false, trial: false } }
    server({ 'GET /session': OWNER, 'GET /skills': { ...SKILLS, items: [...SKILLS.items, gone], counts: { ...SKILLS.counts, deleted: 1 } } })
    renderApp('/skills')
    await screen.findByText('Kỹ năng riêng: nhac-gia')
    expect(screen.queryByText('Kỹ năng riêng: cu')).toBeNull()
    await userEvent.click(screen.getByRole('tab', { name: /Đã xoá/ }))
    expect(await screen.findByText('Kỹ năng riêng: cu')).toBeInTheDocument()
    expect(screen.queryByText('Kỹ năng riêng: nhac-gia')).toBeNull()
  })
})
