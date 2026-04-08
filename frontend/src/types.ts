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

export type Schedule = {
  id: string
  user_id: string
  title: string
  type: ScheduleType
  start_time: string
  end_time: string
  location: string | null
  description: string | null
  is_completed: boolean
  google_synced?: boolean
  created_at: string
  updated_at: string
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
