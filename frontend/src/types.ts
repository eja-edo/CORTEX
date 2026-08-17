export type AuthMode = 'login' | 'register'

export type WorkspaceRole = 'owner' | 'editor' | 'viewer'

export type Workspace = {
  id: string
  owner_id: string
  name: string
  is_personal: boolean
  my_role: WorkspaceRole
}

export type User = {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ScheduleType = 'CLASS' | 'DEADLINE' | 'EXAM' | 'PERSONAL' | 'CRON_EVENT'

export type RecurrenceFreq = 'NONE' | 'DAILY' | 'WEEKLY' | 'MONTHLY'

export type RecurrenceRule = {
  freq: RecurrenceFreq
  interval?: number  // Always 1 - kept for backward compatibility
  until?: string    // ISO datetime
  count?: number
  tzid: string
}

export type ReminderMethod = 'push' | 'email'

export type ReminderConfig = {
  minutes_before: number
  method: ReminderMethod
}

export type ReminderResponse = {
  id: string
  minutes_before: number
  method: ReminderMethod
  scheduled_at: string
  status: 'pending' | 'sent' | 'failed' | 'cancelled'
}

export type EditScope = 'this_only' | 'this_and_after' | 'all'

export type Schedule = {
  id: string | null  // null for virtual instances
  user_id: string
  title: string
  type: ScheduleType
  start_time: string
  end_time: string
  location: string | null
  description: string | null
  is_completed: boolean
  recurrence?: RecurrenceRule | null
  reminders?: ReminderConfig[] | ReminderResponse[]  // Accept both input and output types
  is_recurring?: boolean
  is_exception?: boolean
  is_cancelled?: boolean
  recurrence_id?: string | null
  original_start_time?: string | null
  is_virtual?: boolean
  google_synced?: boolean
  version?: number
  created_at: string | null  // null for virtual instances
  updated_at: string | null  // null for virtual instances
}

export type TaskStatus = 'pending_confirm' | 'todo' | 'in_progress' | 'done' | 'cancelled' | 'rejected'

export type TaskPriority = 'low' | 'medium' | 'high' | 'urgent'

export type Task = {
  id: string
  user_id: string
  title: string
  status: TaskStatus
  /** A deadline, not a booked span — a task still consumes time, it never
   * occupies it. Usually a bare day (midnight); can carry a real time (e.g.
   * a checklist item inherits its event's `end_time`). Use `dateOnly()`
   * from `utils/taskDateBuckets` before treating this as a `yyyy-MM-dd`
   * bucket key. */
  due_date: string | null
  priority: TaskPriority | null
  description: string | null
  related_event_id: string | null
  /** A task's own checklist — self-referential, same shape as
   * `related_event_id`. Null for a top-level task. */
  parent_task_id: string | null
  source_conversation_id: string | null
  source_message_id: string | null
  /** When this task last became `done` — null once reopened. The one field
   * that tells "finished today" from "finished on some earlier day"; see
   * `isVisibleToday` in `utils/taskDateBuckets`. */
  completed_at: string | null
  created_at: string
  updated_at: string
}

/**
 * One row on the calendar, from either table (Milestone 2.6).
 *
 * `render_as` comes from the server on purpose — the client must not
 * re-derive it from `kind`, or the two mappings can drift and a task ends up
 * drawn as a block of booked time.
 */
export type CalendarItem = {
  id: string
  kind: 'schedule' | 'task'
  render_as: 'block' | 'marker'
  title: string
  /** schedule only */
  start_time: string | null
  /** schedule only */
  end_time: string | null
  /** task only — usually midnight of the due day, but can carry a real
   * time; `render_as: 'marker'` is what keeps it from ever being drawn as
   * a clock position on the calendar, not the value itself */
  due_date: string | null
  status: string
  /** schedule only */
  location: string | null
}

export type TokenPair = {
  accessToken: string
  refreshToken: string
}

export type ScheduleListResponse = {
  items: Schedule[]
  total: number
}

export type GoogleCalendarStatus = {
  connected: boolean
  provider: 'GOOGLE'
  calendar_id: string | null
  granted_scopes: string[]
  last_synced_at: string | null
  has_sync_token: boolean
  channel_expiration: string | null
  last_sync_error: string | null
  needs_reauth: boolean
}

export type SyncUpdateEvent = {
  event: 'sync.update'
  source: string
  trigger: string
  stats: {
    created?: number
    updated?: number
    deleted?: number
    skipped?: number
  }
  detail?: string | null
  occurred_at: string
}

// ============================================================================
// Phase 5: Agent Memory and Proactive Suggestions
// ============================================================================

export type AgentMessageRole = 'user' | 'assistant' | 'tool'

export type AgentMessage = {
  id: string
  role: AgentMessageRole
  content: string
  context?: Record<string, unknown> | null
  tool_name?: string
  tool_input?: string
  tool_output?: string
  created_at: string
}

export type AgentConversation = {
  id: string
  workspace_id: string | null
  title: string
  summary: string | null
  message_count: number
  total_tokens: number
  created_at: string
  updated_at: string
}

export type ConversationListItem = {
  id: string
  workspace_id: string | null
  title: string
  message_count: number
  has_summary: boolean
  updated_at: string
  created_at: string
}

export type TokenBudgetStatus = {
  used: number
  limit: number  // 100,000
  remaining: number
  percentage: number  // 0-100
}

export type AgentChatRequest = {
  message: string
  conversation_id?: string
  workspace_id?: string
}

export type AgentChatResponse = {
  conversation_id: string
  reply: string
}

// ============================================================================
// Phase 4: Visual Workflow Builder
// ============================================================================

export type WorkflowStatus = 'draft' | 'active' | 'paused' | 'archived'

export type TriggerType = 'internal_event' | 'webhook' | 'schedule' | 'manual'

export type NodePosition = {
  x: number
  y: number
}

export type WorkflowNodeDef = {
  id: string
  type: string
  position: NodePosition
  data: Record<string, unknown>
}

export type WorkflowEdgeDef = {
  id: string
  source: string
  target: string
  source_handle?: string
  target_handle?: string
}

export type WorkflowDefinitionSchema = {
  nodes: WorkflowNodeDef[]
  edges: WorkflowEdgeDef[]
  variables: Record<string, unknown>
}

// Milestone 4.2 — Trigger Catalog. GET /api/v1/actions/triggers/catalog.
// Replaces the frontend's own hardcoded event-type list, which was the
// same "second independently-maintained list" drift risk 1.9 fixed once
// already between the backend and workflow_service.
export type TriggerCatalogEntry = {
  event_type: string
  label_vi: string
  has_direct_backend_delivery: boolean
}

// A duplicate-delivery risk (Milestone A3) — see workflow_service's
// app/services/workflow_conflicts.py. Informational only, never blocks
// activation.
export type WorkflowConflict = {
  kind: 'backend_direct' | 'workflow'
  event_type: string
  action_type: string
  message: string
  conflicting_workflow_id: string | null
  conflicting_workflow_name: string | null
}

export type WorkflowResponse = {
  id: string
  user_id: string
  workspace_id: string | null
  name: string
  description: string | null
  status: WorkflowStatus
  version: number
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  definition: WorkflowDefinitionSchema
  webhook_url: string | null
  webhook_secret: string | null
  created_at: string
  updated_at: string
  // null/undefined = not computed for this response. Populated by
  // /activate and GET /workflows/{id}/conflicts — see A3.
  warnings?: WorkflowConflict[] | null
}

export type WorkflowListResponse = {
  items: WorkflowResponse[]
  total: number
  page: number
  page_size: number
}

export type WorkflowCreatePayload = {
  name: string
  description?: string
  workspace_id?: string
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  definition: WorkflowDefinitionSchema
}

export type WorkflowUpdatePayload = {
   name?: string
   description?: string
   status?: WorkflowStatus
   trigger_config?: Record<string, unknown>
   definition?: WorkflowDefinitionSchema
}

// Multi-trigger support: supplementary triggers on top of a workflow's
// primary trigger_type/trigger_config (see WorkflowResponse above).
export type WorkflowTriggerResponse = {
  id: string
  workflow_id: string
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
  is_active: boolean
  webhook_url: string | null
  webhook_secret: string | null
  created_at: string
  updated_at: string
}

export type WorkflowTriggerCreatePayload = {
  trigger_type: TriggerType
  trigger_config: Record<string, unknown>
}

export type WorkflowTriggerUpdatePayload = {
  trigger_config?: Record<string, unknown>
  is_active?: boolean
}

export type NotificationBlock =
   | { type: 'text'; text: string }
   | { type: 'image'; url: string; alt?: string }
   | { type: 'html'; html: string }
   | { type: 'code'; language?: string; content: string }
   | { type: 'markdown'; text: string }

export type NotificationActionDef = {
   label: string
   action: 'navigate' | 'dismiss' | 'callback'
   url?: string
   payload?: Record<string, unknown>
}

export type NotificationResponse = {
   id: string
   user_id: string
   type: string
   title: string
   body: string | null
   content: NotificationBlock[]
   actions: NotificationActionDef[]
   payload: Record<string, unknown>
   read_at: string | null
   created_at: string
   // Null for notifications created outside the Attention Gate's gated
   // path. When set, attention_log_id is what to send back to
   // POST /attention-log/{id}/response on dismiss/click (Feedback Loop, 6.9).
   reason_key: string | null
   attention_level: 'silent' | 'inform' | 'recommend' | 'ask' | 'act' | null
   attention_log_id: string | null
}

export type NotificationListResponse = {
   items: NotificationResponse[]
   total: number
}

// Milestone 6.2 — quiet hours. Both fields null means not configured.
export type UserPreferencesResponse = {
   quiet_hours_start: string | null
   quiet_hours_end: string | null
}

// Redesigned 4.5 / A2 follow-up: per-reason on/off, backend-side (see
// docs/planning-v3.md's A2 section for why this isn't a workflow toggle).
// dismiss_count/effective_level are the Feedback Loop's visibility half
// (Milestone 6.9 M2) — effective_level is base_level after auto-downgrade.
export type ReasonPreference = {
   reason_key: string
   description: string
   base_level: AttentionLevel
   enabled: boolean
   dismiss_count: number
   effective_level: AttentionLevel
}

export type AttentionLevel = 'silent' | 'inform' | 'recommend' | 'ask' | 'act'

// Delivery channels (bước 0 + M1). A channel is a way Cortex can reach the
// user outside an open browser tab — see docs/planning-v3.md §XI.
//
// `address_hint` is a masked tail, never the full address: push endpoints
// and chat ids are bearer-ish capabilities, and the settings list only
// needs enough to tell two devices apart.
export type UserChannel = {
   id: string
   channel: 'in_app' | 'push' | 'telegram' | 'email' | 'slack' | 'mezon' | 'webhook'
   label: string | null
   address_hint: string
   enabled: boolean
   verified: boolean
   min_level: AttentionLevel
   last_used_at: string | null
   created_at: string
}

// One-time code the user types into the chat app. Minted here, where they
// are already authenticated — never the other way round, since chat user
// ids are visible to anyone and would prove nothing.
export type ChannelLinkCode = {
   code: string
   channel: string
   expires_in: number
   instruction: string
}
