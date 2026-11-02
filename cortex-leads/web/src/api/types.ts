export type Role = 'staff' | 'owner'
export interface Me {
  role: Role
  staff_ref: string | null
  tenant: string
  timezone: string
  csrf: string
  email: string
  name: string
  must_change_password: boolean
  permissions: string[]
  ai: 'running' | 'paused' | 'none'
  mode: 'auto' | 'manual' | 'mixed'
  needs_person: number
}

export type ConvFilter = 'need_human' | 'waiting' | 'silent' | 'all'
export interface ConvItem {
  id: string
  name: string
  snippet: string
  at: string
  channel: string
  badges: string[]
  state: string
}
export interface ConvList {
  items: ConvItem[]
  counts: Record<ConvFilter, number>
}
export interface Draft {
  id: string
  text: string
  claims: { value: string | number; source_id: string }[]
  needs_human: boolean
  route: 'channel' | 'offchannel'
  turn: boolean
  reason: string | null
  created_at: string
}
export interface Slot {
  code: string
  name: string
  ngay: string | null
  gio: string | null
  con_cho: number
}
export interface Conversation {
  id: string
  name: string
  channel: string
  state: string
  intent: string | null
  owner: string | null
  decision_maker: string | null
  promised_date: string | null
  window: { open: boolean; basis: string | null; expires_at: string | null }
  messages: { id: string; role: 'customer' | 'staff' | 'bot'; text: string; at: string }[]
  drafts: Draft[]
  facts: { id: string; kind: string; text: string; status: 'active' | 'candidate'; evidence: number; by_ai: boolean }[]
  bookings: { id: string; slot: string; at: string; by_ai: boolean }[]
  open_slots: Slot[]
  log: { at: string; label: string; skill: string | null }[]
}

export type SkillStatus = 'live' | 'shadow' | 'draft' | 'retired'
export interface SkillCan {
  trial: boolean
  live: boolean
  off: boolean
  again: boolean
  edit: boolean
  delete: boolean
  restore: boolean
}
export interface SkillItem {
  id: string
  name: string
  version: number
  description: string
  trigger: string
  status: SkillStatus
  source: 'custom' | 'card' | 'system'
  sandbox: string
  runs: number
  blocked: number
  ready: boolean
  can: SkillCan
  deleted: boolean
}
export interface SkillList {
  items: SkillItem[]
  counts: Record<'all' | SkillStatus | 'deleted', number>
  min_trial_runs: number
}
export interface SkillHistory {
  id: string
  at: string
  actor: string
  summary: string
  changes: { field: string; before: unknown; after: unknown }[]
  restorable: boolean
}
export interface SkillDetail extends SkillItem {
  created_at: string
  deleted_at: string | null
  deleted_by: string | null
  form: SkillSpec | null
  history: SkillHistory[]
  min_trial_runs: number
  trial_drafts: { asked: string; text: string; blocked: boolean }[]
  tools: string[]
  must_handoff: string[]
  never_say_count: number
  limits: Record<string, unknown>
  sends: boolean
}
export interface FormOptions {
  templates: { id: 'khach_im' | 'dung_hen'; label: string }[]
  intents: { id: string; label: string }[]
  has_sandbox: boolean
  locked: string[]
  always: string
}
export interface SkillSpec {
  template: 'khach_im' | 'dung_hen'
  slug: string
  description: string
  instructions: string
  after_hours: number
  intent: string | null
  max_touches: number
  never_say: string[]
  must_handoff: string[]
  examples?: { khach: string; tra_loi: string }[]
}
export interface SkillPreview {
  errors: string[]
  summary: { trigger: string; tools: string[]; locked: string[]; always: string; never_say_count: number; must_handoff: string[] }
}

export interface SandboxItem {
  id: string
  title: string
  purpose: string
  about: string
  status: 'active' | 'paused'
  send_mode: 'auto' | 'manual'
  customer_facing: boolean
  flow: string | null  // what comes in and where the output goes, for sandboxes that do not talk to customers
  budget: { runs_per_day: number | null; tokens_per_day: number | null; drafts_per_staff_per_day: number | null }
  usage: { runs: number; tokens: number }
  skills: { live: number; shadow: number }
  channels: { kind: string; status: string; sends: boolean }[]
}
export interface SandboxTemplate {
  id: 'customer_care' | 'owner_digest' | 'student_care'
  label: string
  description: string
  available: boolean
  reason?: string
}
export interface SandboxList {
  items: SandboxItem[]
  templates: SandboxTemplate[]
}

export interface Proposal {
  id: string
  kind: string
  signal: string
  sandbox: string
  skill: string | null
  change: { field: string; from: unknown; to: unknown } | null
  action: string
  evidence: string[]
  danger: boolean
}
export interface ChatTurn {
  role: 'user' | 'assistant'
  content: string
}
export interface ChatReply {
  reply: string
  refused: boolean
  verified: boolean
}

export interface AuditItem {
  id: string
  seq: number
  at: string
  actor: string
  role: string
  category: string
  action: string
  result: 'success' | 'denied' | 'failed'
  summary: string
  object: { type: string; id: string; label: string | null } | null
  ip: string | null
  has_metadata: boolean
}
export interface AuditDetail extends AuditItem {
  user_agent: string | null
  request_id: string | null
  session_id: string | null
  metadata: Record<string, unknown>
  hash: string
}
export interface AuditList {
  items: AuditItem[]
  total: number
  page: number
  page_size: number
  pages: number
  page_sizes: number[]
  actors: string[]
  categories: Record<string, string>
}
export interface AuditQuery {
  page: number
  page_size: number
  date_from?: string
  date_to?: string
  actor?: string
  category?: string
  result?: string
  q?: string
}
export interface AuditVerify {
  ok: boolean
  checked: number
  total?: number
  first_bad?: string
}

export type ToolLevel = 'read' | 'internal' | 'customer' | 'external'
export interface ToolRow {
  name: string
  label: string
  about: string
  level: ToolLevel
  level_label: string
}
export interface ToolList {
  items: (ToolRow & { sandboxes: { id: string; title: string; on: boolean }[]; skills: number })[]
  levels: Record<ToolLevel, string>
  counts: { tools: number; sources: number; channels: number }
}
export type Cell = 'uses' | 'allowed' | 'blocked' | 'off' | 'locked'
export interface SandboxDetail {
  id: string
  title: string
  purpose: string
  about: string
  status: 'active' | 'paused'
  profile: { id: string; version: number; ceiling: string; max_tool_calls: number }
  inputs: {
    channels: { kind: string; status: string; sends: boolean }[]
    catalog_items: number
    sources: { id: string; name: string; kind: string; status: string }[]
  }
  facing: { customer: boolean; tools: boolean }  // what this kind of sandbox has, so the page shows only that
  feeds: { id: string; kind: string; label: string; where: string; active: boolean; since: string; noun: string; unit: string; lessons: { done: number; failed: number; waiting: number } }[]
  pushes: { id: string; kind: string; label: string; where: string; active: boolean }[]
  tools: (ToolRow & { on: boolean; skills: string[] })[]
  skills: { id: string; name: string; status: SkillStatus; source: 'custom' | 'system'; trigger: string; cells: Record<string, Cell>; uses: number; total: number }[]
  levels: Record<ToolLevel, string>
  send: {
    mode: 'auto' | 'manual'
    auto_possible: boolean
    skills: { name: string; can_auto: boolean; effective: 'auto' | 'manual'; why: string }[]
    channels: { kind: string; can_send: boolean; problems: string[] }[]
  }
}
export interface ToolInSandbox extends ToolRow {
  on: boolean
  skills: string[]
  sandbox: string
  safety: string[]
  if_off: string | null
}

export type SourceState = 'active' | 'locked' | 'alert' | 'deleted'
export interface SourceItem {
  id: string
  name: string
  kind: 'http_readonly' | 'mcp'
  kind_label: string
  host: string
  description: string
  state: SourceState
  alert: string | null
  alert_code: string | null
  pinned_tools: string[]
  sandbox: { id: string; title: string } | null
  deleted_at: string | null
  deleted_by: string | null
  calls_7d: number
  errors_7d: number
  last_at: string | null
}
export interface SourceList {
  items: SourceItem[]
  counts: { all: number; deleted: number }
  attachable: { id: string; title: string }[]
  blocked: { id: string; title: string }[]
}
export interface SourceDetail extends SourceItem {
  url: string
  allow_hosts: string[]
  auth_saved: boolean
  auth_header: string | null
  pin: string
  pin_ok: boolean
  attachable: { id: string; title: string }[]
}
export interface NewSource {
  kind: 'http_readonly' | 'mcp'
  name: string
  description: string
  url: string
  host: string
  auth_header?: string
  secret?: string
  sandbox_id: string
  tool?: string
  arg?: string
}
export interface McpTool {
  name: string
  description: string
  read_only: boolean
}

export interface Member {
  id: string
  email: string
  name: string
  role: Role
  staff_ref: string
  status: 'active' | 'disabled'
  must_change_password: boolean
  last_login_at: string | null
  created_at: string
  sessions: number
  you: boolean
}
export interface MySession {
  id: string
  current: boolean
  created_at: string
  last_seen_at: string
  ip: string | null
  user_agent: string | null
}

export interface LessonItem {
  id: string; storage: 'drive' | null; origin: string | null; has_media: boolean; media_type: 'video' | 'audio' | null; language: string | null; name: string; status: 'queued' | 'working' | 'done' | 'failed'; status_label: string; attempts: number; sandbox: string
  created_at: string; finished_at: string | null; has_recap: boolean; problem: string | null; class_id: string; class_name: string | null
  released: boolean; released_at: string | null; released_by: string | null; awaiting_release: boolean  // a recap of a class set to "review" waits here for a person
  classroom: { state: 'posted' | 'waiting' | 'held' | 'failed'; course: string | null; published: boolean; error: string | null } | null
}
export interface LessonList { items: LessonItem[]; limit: number; can_upload: boolean; max_mb: number; classes: { id: string; name: string; can_upload: boolean; lessons: number }[] }
export type RecapMode = 'auto' | 'review'
export type GradingMode = 'manual' | 'review' | 'auto_write'
export interface ClassItem {
  id: string; name: string; sandbox_id: string | null; sandbox: string; grader_sandbox_id: string | null; account: string | null; account_id: string | null; linked: boolean; active: boolean; since: string; folder: string; folder_url: string | null; owned: boolean; can_upload: boolean
  webhook: string | null; has_webhook: boolean; lessons: { done: number; failed: number; waiting: number; held: number }
  classroom: { course_id: string; course: string | null; account_id: string | null } | null
  policy: { recap_mode: RecapMode; grading_mode: GradingMode; assignment_post_mode: 'manual' }
  can_grade: boolean; grading: { assignments: number; to_review: number; pending: number; waiting: number; done: number }
}
export interface LessonDetail extends LessonItem {
  recap: { summary: string; topics: string[]; sections?: { title: string; points: string[] }[]; homework: { task: string; due: string | null }[]; class_notes: string } | null
  message: string | null; transcript: string | null; video_url: string | null
}

export type GradeStatus = 'pending' | 'queued' | 'working' | 'proposed' | 'approved' | 'rejected' | 'skipped' | 'failed'
export interface GradeItem {
  id: string; class_id: string; assignment_id: string; work_title: string; student: string; status: GradeStatus; status_label: string; ours: boolean; max_points: number | null
  total: number | null; flags: string[]; problems: number; reason: string | null; written: boolean; created_at: string
}
export interface GradeList { items: GradeItem[]; counts: Record<'pending' | 'proposed' | 'approved' | 'rejected' | 'skipped' | 'failed' | 'waiting', number>; limit: number }
export interface Criterion { id: string; label: string; points: number; descriptor: string }
export interface GradeCriterion { id: string; label: string; points: number; score: number; proposed: number | null; quote: string; comment: string; verified: boolean }
export interface GradeProposal { criteria: GradeCriterion[]; total: number; max_points: number; feedback: string; concerns: string[]; problems: string[]; flags: string[]; transcript?: string }
export interface GradeDetail extends GradeItem {
  content: string | null
  content_kind: string[]  // what the work was read from: text, pdf, docx, audio, video
  guide: { title: string; max_points: number; criteria: Criterion[]; answer_key: string | null; check_prompt?: string | null } | null
  proposal: GradeProposal | null
  final: { scores: Record<string, number>; total: number; max_points: number; write: string; feedback: string } | null
  decided_by: string | null; decided_at: string | null
}
export interface GradeDecision { action: 'approve' | 'reject'; scores?: Record<string, number>; feedback?: string }  // where the grade goes is the class's policy, not a choice per submission
export interface AssignmentDraft {
  id: string; class_id: string; course: string | null; title: string; description: string; max_points: number; criteria: Criterion[]; answer_key: string | null; check_prompt?: string | null; language: string | null; origin: 'teacher' | 'ai'; materials: Material[]
  status: 'draft' | 'created' | 'rejected' | 'failed'; due: string | null; publish: boolean; error: string | null; created_by: string | null; created_at: string
}
export type Material = { kind: 'drive'; id: string; title: string; share: 'VIEW' | 'EDIT' | 'STUDENT_COPY' } | { kind: 'link'; url: string; title: string }
export interface MaterialIn { url: string; title?: string; share: 'VIEW' | 'EDIT' | 'STUDENT_COPY' }
export interface AssignmentList { items: AssignmentDraft[]; sources: { id: string; label: string }[] }
export interface NewAssignment { class_id: string; title: string; description: string; max_points: number; criteria: Criterion[]; answer_key: string | null; check_prompt?: string | null; language: string | null; materials: MaterialIn[] }

export interface GoogleAccount {
  id: string; label: string; email: string | null; status: 'active' | 'revoked'; can: { classroom: boolean; classroom_post: boolean; drive: boolean; drive_read: boolean }
  connected_at: string; connected_by: string; used_by: { kind: 'classroom' | 'drive' | 'folder'; name: string; sandbox: string }[]
  refs: GoogleRef[]
}
/** One thing that signs in as an account: it keeps its data when the account is deleted and waits to be linked to another. */
export interface GoogleRef { kind: 'folder' | 'post' | 'classroom' | 'target'; id: string; name: string; active: boolean }
export interface GoogleList {
  configured: boolean; items: GoogleAccount[]; sources: GoogleSource[]; sandboxes: { id: string; title: string; purpose: string }[]
  kinds: { id: 'classroom' | 'classroom_post' | 'drive' | 'drive_read'; label: string }[]
}
export interface GoogleSource {
  kind: 'classroom' | 'drive' | 'folder'; id: string; name: string; sandbox: string; active: boolean; account: string | null; account_id: string | null; legacy: boolean
}
export interface GoogleFolder { id: string; name: string; connected: boolean }
export interface GoogleCourse { id: string; name: string; section: string; connected: boolean }

/** One piece of work of a class, with where its submissions stand: the rows of a class page's "Bài tập" tab. */
export interface ClassAssignment {
  id: string; title: string; state: 'draft' | 'created'; ours: boolean; gradable: boolean; max_points: number | null; due: string | null; created_at: string
  counts: Record<'pending' | 'proposed' | 'approved' | 'rejected' | 'skipped' | 'failed' | 'waiting', number>; submissions: number
  description: string | null; criteria: Criterion[]; materials: Material[]; answer_key: string | null; check_prompt: string | null; language: string | null
}
export interface ClassAssignments { class: { id: string; name: string; grading_mode: GradingMode }; items: ClassAssignment[] }

// --- Cài đặt (WP39-43) ---
export interface BusinessSettings {
  name: string
  timezone: string
  hours: { start: string; end: string }
  hours_differ: boolean
  ai_name: string | null
  disclosure: string
}
export interface NotifyTarget {
  id: string
  kind: 'telegram' | 'mezon'
  address: string  // masked by the server
  label: string | null
  sandbox_id: string | null
  sandbox: string | null
  created_at: string
}
export interface NotifyTargets {
  items: NotifyTarget[]
  telegram_ready: boolean
  sandboxes: { id: string; title: string }[]
}
export interface ChannelItem {
  id: string
  kind: string
  status: 'active' | 'disabled'
  sandbox: string | null
  sandbox_id: string
  sends: boolean
  created_at: string
  last_event_at: string | null
}
export interface Channels {
  items: ChannelItem[]
  kinds: string[]
  sandboxes: { id: string; title: string }[]
  ingest_url: string | null
}
export interface NewChannelResult {
  id: string
  kind: string
  secret: string
  ingest_url: string | null
}
export interface AiOverview {
  disclosure: string
  sandboxes: { id: string; title: string; send_mode: 'auto' | 'manual'; status: 'active' | 'paused'; skills: { name: string; status: string; sends: boolean }[]; never_say: string[]; must_handoff: string[] }[]
}
export interface OnboardingStep {
  id: string
  title: string
  done: boolean
  count: number
  href: string | null
  hint: string
}
export interface Onboarding {
  steps: OnboardingStep[]
  complete: boolean
  done: number
}
export interface EraseResult {
  erased: Record<string, number>
  not_reached: string[]
}
