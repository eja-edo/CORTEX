import { useCallback, useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Circle, LogOut, X } from 'lucide-react'
import { startOfWeek, endOfWeek } from 'date-fns'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import './App.css'
import { AuthPanel } from './components/AuthPanel'
import { ScheduleForm } from './components/ScheduleForm'
import { CalendarView } from './components/CalendarView'
import { NoteSidebar, type NoteItem } from './components/NoteSidebar'
import type { Schedule, TokenPair, User, ScheduleListResponse } from './types'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const PKCE_CLIENT_ID = 'cortex-web'
const PKCE_REDIRECT_URI = window.location.origin + '/auth/callback'
const TOKEN_STORAGE_KEY = 'cortex_tokens'

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function getRangeForCurrentWeek(): { startDate: string; endDate: string } {
  const now = new Date()
  const start = startOfWeek(now, { weekStartsOn: 1 }) // Monday
  const end = endOfWeek(now, { weekStartsOn: 1 }) // Sunday

  start.setHours(0, 0, 0, 0)
  end.setHours(23, 59, 59, 999)

  return {
    startDate: toLocalInputDateTime(start),
    endDate: toLocalInputDateTime(end),
  }
}

function toIsoDateTime(localDateTime: string): string {
  return new Date(localDateTime).toISOString()
}

function readStoredTokens(): TokenPair | null {
  const raw = window.localStorage.getItem(TOKEN_STORAGE_KEY)
  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw) as TokenPair
    if (parsed.accessToken && parsed.refreshToken) {
      return parsed
    }
    return null
  } catch {
    return null
  }
}

function writeStoredTokens(tokens: TokenPair | null): void {
  if (!tokens) {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY)
    return
  }

  window.localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens))
}

function randomUrlSafeString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength)
  window.crypto.getRandomValues(bytes)

  let output = ''
  for (const byte of bytes) {
    output += String.fromCharCode(byte)
  }

  return btoa(output)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
}

async function createCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(verifier)
  const hashBuffer = await window.crypto.subtle.digest('SHA-256', data)
  const bytes = new Uint8Array(hashBuffer)

  let output = ''
  for (const byte of bytes) {
    output += String.fromCharCode(byte)
  }

  return btoa(output)
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '')
}

function App() {
  const [tokens, setTokens] = useState<TokenPair | null>(() => readStoredTokens())
  const [user, setUser] = useState<User | null>(null)
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [statusMessage, setStatusMessage] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [isBusy, setIsBusy] = useState<boolean>(false)
  const [isCreateEventOpen, setIsCreateEventOpen] = useState<boolean>(false)

  const weekRange = useMemo(() => getRangeForCurrentWeek(), [])
  const [startDate, setStartDate] = useState<string>(weekRange.startDate)
  const [endDate, setEndDate] = useState<string>(weekRange.endDate)

  const [recentNotes, setRecentNotes] = useState<NoteItem[]>(() => [
    {
      id: 'note-1',
      date: '4/6/2026',
      contentHtml: `<p>Bắt đầu đi xin dấu thực tập</p><ul><li><strong>Thực tập hệ thống thông tin quản lý</strong></li><li><strong>Thực tập hệ thống thông tin tích hợp</strong></li><li><strong>Thực tập quản trị dự án phần mềm</strong></li></ul><p>https://docs.google.com/document/d/1P9ldp5hSor13MthUFvPvk2hVU2i9IFVQ/edit</p>`,
    },
    {
      id: 'note-2',
      date: '4/6/2026',
      contentHtml:
        '<p>day 4/6/2026</p><ul><li><strong>Todo</strong></li><li><strong>lưu tất cả participant trong room</strong></li></ul><p>Add tất cả participant vào room data phục vụ sync.</p>',
    },
    {
      id: 'note-3',
      date: '4/3/2026',
      contentHtml:
        '<p><strong>Release 2026040x</strong></p><p>Checklist triển khai bản phát hành và các hạng mục cần rà soát.</p>',
    },
  ])

  const handleNoteChange = useCallback((id: string, contentHtml: string) => {
    setRecentNotes((prev) => prev.map((n) => (n.id === id ? { ...n, contentHtml } : n)))
  }, [])

  useEffect(() => {
    writeStoredTokens(tokens)
  }, [tokens])

  useEffect(() => {
    if (!tokens) {
      setUser(null)
      setSchedules([])
      return
    }

    void fetchCurrentUser(tokens)
    void fetchSchedules(tokens)
  }, [tokens, startDate, endDate])

  async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init)
    const text = await response.text()
    const body = text ? JSON.parse(text) : null

    if (!response.ok) {
      const detail = body?.detail ?? `Request failed (${response.status})`
      throw new Error(detail)
    }

    return body as T
  }

  async function refreshToken(currentRefreshToken: string): Promise<TokenPair> {
    const payload = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(
      `${API_BASE_URL}/auth/refresh`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: currentRefreshToken }),
      },
    )

    return {
      accessToken: payload.access_token,
      refreshToken: payload.refresh_token,
    }
  }

  async function requestWithAuth<T>(path: string, init?: RequestInit): Promise<T> {
    if (!tokens) {
      throw new Error('Please login first')
    }

    const headers = new Headers(init?.headers ?? {})
    headers.set('Authorization', `Bearer ${tokens.accessToken}`)

    let response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers,
    })

    if (response.status === 401) {
      const newTokens = await refreshToken(tokens.refreshToken)
      setTokens(newTokens)

      const retryHeaders = new Headers(init?.headers ?? {})
      retryHeaders.set('Authorization', `Bearer ${newTokens.accessToken}`)

      response = await fetch(`${API_BASE_URL}${path}`, {
        ...init,
        headers: retryHeaders,
      })
    }

    const text = await response.text()
    const body = text ? JSON.parse(text) : null

    if (!response.ok) {
      const detail = body?.detail ?? `Request failed (${response.status})`
      throw new Error(detail)
    }

    return body as T
  }

  async function fetchCurrentUser(activeTokens: TokenPair): Promise<void> {
    try {
      const profile = await fetch(`${API_BASE_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${activeTokens.accessToken}` },
      })

      if (profile.status === 401) {
        const nextTokens = await refreshToken(activeTokens.refreshToken)
        setTokens(nextTokens)

        const retried = await fetch(`${API_BASE_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${nextTokens.accessToken}` },
        })

        if (!retried.ok) {
          throw new Error('Cannot load profile')
        }

        const retriedBody = (await retried.json()) as User
        setUser(retriedBody)
        return
      }

      if (!profile.ok) {
        throw new Error('Cannot load profile')
      }

      const body = (await profile.json()) as User
      setUser(body)
    } catch {
      setTokens(null)
      setUser(null)
      setErrorMessage('Your session expired. Please login again.')
    }
  }

  async function handleRegister(name: string, email: string, pass: string): Promise<void> {
    setErrorMessage('')
    setStatusMessage('')
    setIsBusy(true)

    try {
      await requestJson<User>(`${API_BASE_URL}/auth/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email,
          password: pass,
          full_name: name,
        }),
      })

      setStatusMessage('Account created. You can login now.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Register failed')
    } finally {
      setIsBusy(false)
    }
  }

  async function handleLogin(email: string, pass: string): Promise<void> {
    setErrorMessage('')
    setStatusMessage('')
    setIsBusy(true)

    try {
      const codeVerifier = randomUrlSafeString(64).slice(0, 96)
      const codeChallenge = await createCodeChallenge(codeVerifier)

      const authorize = await requestJson<{ code: string }>(`${API_BASE_URL}/auth/authorize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email,
          password: pass,
          client_id: PKCE_CLIENT_ID,
          redirect_uri: PKCE_REDIRECT_URI,
          code_challenge: codeChallenge,
          code_challenge_method: 'S256',
          state: randomUrlSafeString(24),
        }),
      })

      const tokenPair = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(
        `${API_BASE_URL}/auth/token`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code: authorize.code,
            code_verifier: codeVerifier,
            client_id: PKCE_CLIENT_ID,
            redirect_uri: PKCE_REDIRECT_URI,
          }),
        },
      )

      setTokens({
        accessToken: tokenPair.access_token,
        refreshToken: tokenPair.refresh_token,
      })
      setStatusMessage('Login successful.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Login failed')
    } finally {
      setIsBusy(false)
    }
  }

  async function fetchSchedules(activeTokens?: TokenPair): Promise<void> {
    const sessionTokens = activeTokens ?? tokens
    if (!sessionTokens) {
      return
    }

    try {
      const data = await requestWithAuth<ScheduleListResponse>(
        `/schedules?start_date=${encodeURIComponent(toIsoDateTime(startDate))}&end_date=${encodeURIComponent(
          toIsoDateTime(endDate),
        )}`,
      )
      setSchedules(data.items)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot load schedules')
    }
  }

  async function handleCreateSchedule(
    schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>,
  ): Promise<void> {
    setErrorMessage('')
    setStatusMessage('')

    try {
      await requestWithAuth<Schedule>('/schedules', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(schedule),
      })

      setStatusMessage('Schedule created.')
      await fetchSchedules()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot create schedule')
    }
  }

  async function handleToggleComplete(item: Schedule): Promise<void> {
    try {
      await requestWithAuth<Schedule>(`/schedules/${item.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_completed: !item.is_completed }),
      })

      await fetchSchedules()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot update schedule')
    }
  }

  async function handleRemoveSchedule(scheduleId: string): Promise<void> {
    try {
      await requestWithAuth<void>(`/schedules/${scheduleId}`, { method: 'DELETE' })
      setStatusMessage('Schedule deleted.')
      await fetchSchedules()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot delete schedule')
    }
  }

  async function handleLogout(): Promise<void> {
    if (!tokens) {
      return
    }

    try {
      await requestJson<{ message: string }>(`${API_BASE_URL}/auth/logout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokens.refreshToken }),
      })
    } catch {
      // Keep local logout behavior even if server-side logout fails.
    }

    setTokens(null)
    setUser(null)
    setSchedules([])
    setStatusMessage('You are logged out.')
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-block">
          <p className="eyebrow">Cortex Planner</p>
        </div>

        <nav className="topbar-nav" aria-label="overview">
        </nav>

        <div className="topbar-actions">
          {user ? <span className="user-chip">{user.email}</span> : null}
          {user ? (
            <button type="button" className="ghost" onClick={handleLogout}>
              <LogOut size={16} /> Logout
            </button>
          ) : null}
        </div>
      </header>

      {statusMessage && !errorMessage ? <p className="status ok"><CheckCircle2 size={18} /> {statusMessage}</p> : null}
      {errorMessage ? <p className="status error"><Circle size={18} /> {errorMessage}</p> : null}

      {!tokens ? (
        <AuthPanel
          onLogin={handleLogin}
          onRegister={handleRegister}
          isBusy={isBusy}
        />
      ) : (
        <section className="dashboard-grid calendar-with-notes">
          <NoteSidebar notes={recentNotes} onNoteChange={handleNoteChange} />
          <CalendarView
            schedules={schedules}
            startDate={startDate}
            endDate={endDate}
            onStartDateChange={setStartDate}
            onEndDateChange={setEndDate}
            onFetch={() => fetchSchedules()}
            onOpenCreateEvent={() => setIsCreateEventOpen(true)}
            onToggleComplete={handleToggleComplete}
            onRemove={handleRemoveSchedule}
          />
        </section>
      )}

      {tokens && isCreateEventOpen ? (
        <div className="create-event-backdrop" onClick={() => setIsCreateEventOpen(false)}>
          <div className="create-event-modal" onClick={(e) => e.stopPropagation()}>
            <div className="create-event-header">
              <h3>Create New Event</h3>
              <button type="button" className="ghost icon-only" onClick={() => setIsCreateEventOpen(false)}>
                <X size={16} />
              </button>
            </div>
            <ScheduleForm onCreate={handleCreateSchedule} weekRange={weekRange} />
          </div>
        </div>
      ) : null}
    </main>
  )
}

export default App

