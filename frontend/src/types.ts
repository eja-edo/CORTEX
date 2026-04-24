export type AuthMode = 'login' | 'register'

export type User = {
  id: string
  email: string
  full_name: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export type ScheduleType = 'CLASS' | 'DEADLINE' | 'EXAM' | 'PERSONAL'

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
