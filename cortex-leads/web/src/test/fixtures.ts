import type { Conversation, ConvList, SandboxList, SkillDetail, SkillList } from '../api/types'

export const LIST: ConvList = {
  counts: { need_human: 1, waiting: 2, silent: 1, all: 3 },
  items: [{ id: 'c1', name: 'Nguyễn Minh Anh', snippet: 'Con em lớp 7 học tiếng anh trên lớp hơi đuối', at: new Date().toISOString(), channel: 'messenger', badges: ['need_human', 'promised:2026-10-25'], state: 'open' }],
}

export const CONV: Conversation = {
  id: 'c1', name: 'Nguyễn Minh Anh', channel: 'messenger', state: 'open', intent: 'Hỏi giá', owner: null, decision_maker: 'bố mẹ', promised_date: null,
  window: { open: true, basis: 'free', expires_at: null },
  messages: [{ id: 'm1', role: 'customer', text: 'Con em lớp 7 học tiếng anh trên lớp hơi đuối', at: new Date().toISOString() }],
  drafts: [{ id: 'd1', text: 'Dạ lớp THCS tối đa 15 bạn, 2 buổi một tuần ạ.', claims: [{ value: 15, source_id: 'THCS' }], needs_human: false, route: 'channel', turn: true, reason: 'Chưa rõ lý do', created_at: new Date().toISOString() }],
  facts: [{ id: 'f1', kind: 'decision_maker', text: 'bo_me', status: 'candidate', evidence: 0, by_ai: true }],
  bookings: [],
  open_slots: [{ code: 'LH-A', name: 'Học thử', ngay: '22/10', gio: '19:00', con_cho: 4 }],
  log: [{ at: new Date().toISOString(), label: 'AI soạn nháp, đã qua bộ kiểm', skill: 'tra-loi-khach' }],
}

const base = { description: 'Hỏi lại khách đã hỏi giá', trigger: 'Khách im 4 giờ (Hỏi giá)', source: 'custom' as const, blocked: 0, can: { trial: false, live: false, off: false, again: false, edit: false, delete: false, restore: false }, deleted: false }
export const SKILLS: SkillList = {
  counts: { all: 3, live: 1, shadow: 1, draft: 1, retired: 0, deleted: 0 }, min_trial_runs: 10,
  items: [
    { ...base, id: 's1', name: 'tra-loi-khach', version: 16, status: 'live', source: 'system', sandbox: 'customer_care', runs: 1204, ready: true },
    { ...base, id: 's2', name: 'tuy-chinh-nhac-gia', version: 2, status: 'shadow', sandbox: 'customer_care', runs: 7, ready: false, can: { trial: false, live: false, off: true, again: false, edit: true, delete: true, restore: false } },
    { ...base, id: 's3', name: 'tuy-chinh-hoc-bong', version: 1, status: 'draft', sandbox: 'customer_care', runs: 0, ready: false, can: { trial: true, live: false, off: false, again: false, edit: true, delete: true, restore: false } },
  ],
}
export const SHADOW: SkillDetail = {
  id: 's2', name: 'tuy-chinh-nhac-gia', version: 2, description: 'x', trigger: 'Khách im 4 giờ (Hỏi giá)', status: 'shadow', source: 'custom', runs: 7, blocked: 1, ready: false,
  min_trial_runs: 10, can: { trial: false, live: false, off: true, again: false, edit: true, delete: true, restore: false }, deleted: false, sandbox: 'Chăm sóc khách', created_at: '2026-10-18T02:05:00Z', deleted_at: null, deleted_by: null, form: null, history: [], tools: ['Soạn nháp cho nhân viên duyệt'], must_handoff: ['giảm giá'], never_say_count: 27, limits: {}, sends: false,
  trial_drafts: [{ asked: 'để em xem lại giá', text: 'Chị ơi lớp IELTS còn chỗ ạ', blocked: false }, { asked: 'giá bao nhiêu', text: 'Khoá IELTS giá 1.000.000đ thôi', blocked: true }],
}

export const SANDBOXES: SandboxList = {
  items: [
    { id: 'sb1', title: 'Chăm sóc khách', purpose: 'customer_care', about: 'Nói chuyện với khách tiềm năng', status: 'active', send_mode: 'manual', customer_facing: true, flow: null, budget: { runs_per_day: 500, tokens_per_day: 20_000_000, drafts_per_staff_per_day: 20 },
      usage: { runs: 142, tokens: 410_000 }, skills: { live: 3, shadow: 1 }, channels: [{ kind: 'messenger', status: 'active', sends: false }] },
  ],
  templates: [
    { id: 'customer_care', label: 'Chăm sóc khách', description: 'Tư vấn, nhắc khách im.', available: true },
    { id: 'owner_digest', label: 'Báo cáo cho chủ', description: 'Báo cáo tuần.', available: true },
    { id: 'student_care', label: 'Hỗ trợ học viên', description: 'Trả lời học viên.', available: false, reason: 'Chưa mở: chờ trung tâm xác nhận nhu cầu' },
  ],
}
