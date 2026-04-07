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
