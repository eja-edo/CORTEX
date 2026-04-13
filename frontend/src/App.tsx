import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, Bold, CheckCircle2, ChevronDown, ChevronRight, Home, Italic, List, LogOut, PanelLeftClose, PanelLeftOpen, Plus, Settings, StickyNote, Underline, Video, X } from 'lucide-react'
import { startOfWeek, endOfWeek } from 'date-fns'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import './App.css'
import { AuthPanel } from './components/AuthPanel'
import { ScheduleForm } from './components/ScheduleForm'
import { CalendarView } from './components/CalendarView'
import { NoteSidebar, type NoteItem } from './components/NoteSidebar'
import { RecordPanel } from './components/RecordPanel'
import type { Schedule, TokenPair, User, ScheduleListResponse, GoogleCalendarStatus, SyncUpdateEvent } from './types'
import { applyMarkdownShortcutOnEnter, htmlToMarkdown, markdownToHtml, plainTextFromMarkdown } from './utils/noteMarkdown'
import { NotificationBell, type AppNotification } from './components/NotificationBell'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
const PKCE_CLIENT_ID = 'cortex-web'
const PKCE_REDIRECT_URI = window.location.origin + '/auth/callback'
const TOKEN_STORAGE_KEY = 'cortex_tokens'
const SSE_TAB_APPID_KEY = 'cortex_sse_appid'

function getOrCreateSseTabAppId(): string {
  const existing = window.sessionStorage.getItem(SSE_TAB_APPID_KEY)
  if (existing) return existing

  const rand = Math.random().toString(36).slice(2, 10)
  const appid = `frontend-${rand}`
  window.sessionStorage.setItem(SSE_TAB_APPID_KEY, appid)
  return appid
}

type ApiNote = {
  id: string
  user_id: string
  content: string
  content_type: string
  position: { x: number; y: number }
  size: { width: number; height: number }
  style: { color: string }
  version: number
  is_deleted: boolean
  created_at: string
  updated_at: string
  rendered_html?: string | null
}

type AppNote = NoteItem & {
  version: number
  updatedAt: string
}

class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function getRangeForCurrentWeek(): { startDate: string; endDate: string } {
  const now = new Date()
  const start = startOfWeek(now, { weekStartsOn: 1 })
  const end = endOfWeek(now, { weekStartsOn: 1 })
  start.setHours(0, 0, 0, 0)
  end.setHours(23, 59, 59, 999)
  return { startDate: toLocalInputDateTime(start), endDate: toLocalInputDateTime(end) }
}

function toIsoDateTime(localDateTime: string): string {
  return new Date(localDateTime).toISOString()
}

function readStoredTokens(): TokenPair | null {
  const raw = window.localStorage.getItem(TOKEN_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw) as TokenPair
    if (parsed.accessToken && parsed.refreshToken) return parsed
    return null
  } catch { return null }
}

function writeStoredTokens(tokens: TokenPair | null): void {
  if (!tokens) { window.localStorage.removeItem(TOKEN_STORAGE_KEY); return }
  window.localStorage.setItem(TOKEN_STORAGE_KEY, JSON.stringify(tokens))
}

function randomUrlSafeString(byteLength: number): string {
  const bytes = new Uint8Array(byteLength)
  window.crypto.getRandomValues(bytes)
  let output = ''
  for (const byte of bytes) output += String.fromCharCode(byte)
  return btoa(output).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

async function createCodeChallenge(verifier: string): Promise<string> {
  const encoder = new TextEncoder()
  const data = encoder.encode(verifier)
  const hashBuffer = await window.crypto.subtle.digest('SHA-256', data)
  const bytes = new Uint8Array(hashBuffer)
  let output = ''
  for (const byte of bytes) output += String.fromCharCode(byte)
  return btoa(output).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '')
}

function noteTitleFromMd(md: string): string {
  if (!md) return 'Untitled note'
  const text = plainTextFromMarkdown(md).replace(/\s+/g, ' ').trim()
  return text.slice(0, 64) || 'Untitled note'
}

function formatNoteDate(isoDateTime: string): string {
  const parsed = new Date(isoDateTime)
  if (Number.isNaN(parsed.getTime())) return 'Unknown date'
  return parsed.toLocaleDateString('vi-VN')
}

function formatDateTimeVi(isoDateTime: string | null): string {
  if (!isoDateTime) return 'Never'
  const parsed = new Date(isoDateTime)
  if (Number.isNaN(parsed.getTime())) return 'Unknown'
  return parsed.toLocaleString('vi-VN')
}

function mapApiNoteToAppNote(note: ApiNote): AppNote {
  return {
    id: note.id,
    contentMd: note.content,
    date: formatNoteDate(note.updated_at),
    version: note.version,
    updatedAt: note.updated_at,
  }
}

// Bug 2 Fix: Only re-render innerHTML when switching notes (note.id changes),
// NOT when contentMd changes from our own typing — that would reset the cursor.
function WorkspaceNoteEditor({
  note,
  onChange,
}: {
  note: NoteItem
  onChange: (id: string, contentMd: string) => void
}) {
  const editorRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<number | null>(null)
  const [wordCount, setWordCount] = useState(0)
  const lastNoteIdRef = useRef<string | null>(null)

  useEffect(() => {
    const el = editorRef.current
    if (!el) return
    // Only re-render HTML when switching to a different note (id changes).
    // If the same note id, the user is typing — don't touch innerHTML or cursor will jump.
    if (lastNoteIdRef.current === note.id) return
    lastNoteIdRef.current = note.id
    el.innerHTML = markdownToHtml(note.contentMd)
    const text = el.textContent ?? ''
    setWordCount(text.trim().split(/\s+/).filter(Boolean).length)
  }, [note.id, note.contentMd])

  useEffect(
    () => () => {
      if (timerRef.current) window.clearTimeout(timerRef.current)
    },
    [],
  )

  const flush = useCallback(() => {
    const el = editorRef.current
    if (!el) return
    onChange(note.id, htmlToMarkdown(el.innerHTML))
  }, [note.id, onChange])

  const queueFlush = useCallback(() => {
    if (timerRef.current) window.clearTimeout(timerRef.current)
    timerRef.current = window.setTimeout(flush, 220)
  }, [flush])

  const handleInput = useCallback(() => {
    queueFlush()
    if (editorRef.current) {
      const text = editorRef.current.textContent ?? ''
      setWordCount(text.trim().split(/\s+/).filter(Boolean).length)
    }
  }, [queueFlush])

  const applyFormat = useCallback(
    (command: string) => {
      const el = editorRef.current
      if (!el) return
      el.focus()
      document.execCommand(command, false)
      queueFlush()
    },
    [queueFlush],
  )

  return (
    <section className="workspace-note">
      <header className="workspace-note-header">
        <div className="workspace-note-meta">
          <h2 className="workspace-note-title">{noteTitleFromMd(note.contentMd)}</h2>
          <div className="workspace-note-info">
            <span className="workspace-note-date">{note.date}</span>
            <span className="workspace-note-sep">·</span>
            <span className="workspace-note-wordcount">{wordCount} từ</span>
          </div>
        </div>
      </header>
      <div className="workspace-note-toolbar">
        <div className="workspace-note-toolbar-group">
          <button type="button" className="workspace-toolbar-btn" onClick={() => applyFormat('bold')} title="Bold">
            <Bold size={14} />
          </button>
          <button type="button" className="workspace-toolbar-btn" onClick={() => applyFormat('italic')} title="Italic">
            <Italic size={14} />
          </button>
          <button type="button" className="workspace-toolbar-btn" onClick={() => applyFormat('underline')} title="Underline">
            <Underline size={14} />
          </button>
          <button type="button" className="workspace-toolbar-btn" onClick={() => applyFormat('insertUnorderedList')} title="List">
            <List size={14} />
          </button>
        </div>
      </div>
      <div
        ref={editorRef}
        className="workspace-note-editor"
        contentEditable
        suppressContentEditableWarning
        data-placeholder="Start writing… use # for headings, ``` for code blocks"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            const el = editorRef.current
            if (!el) return
            if (applyMarkdownShortcutOnEnter(el)) {
              e.preventDefault()
              queueFlush()
            }
          }
        }}
        onInput={handleInput}
        onBlur={flush}
      />
    </section>
  )
}

// Collapsible sidebar section header
function SidebarSection({
  icon,
  label,
  isOpen,
  onToggle,
  isCollapsed,
  children,
}: {
  icon: React.ReactNode
  label: string
  isOpen: boolean
  onToggle: () => void
  isCollapsed: boolean
  children?: React.ReactNode
}) {
  return (
    <div className="sidebar-collapsible-section">
      <button
        type="button"
        className="workspace-sidebar-section-title sidebar-section-toggle"
        onClick={onToggle}
        aria-expanded={isOpen}
        title={label}
      >
        <span className="sidebar-section-toggle-icon">{icon}</span>
        {!isCollapsed && (
          <>
            <span className="sidebar-section-toggle-label">{label}</span>
            <span className="sidebar-section-toggle-chevron">
              {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            </span>
          </>
        )}
      </button>
      {isOpen && !isCollapsed && (
        <div className="sidebar-section-body">{children}</div>
      )}
    </div>
  )
}

function App() {
  const [tokens, setTokens] = useState<TokenPair | null>(() => readStoredTokens())
  const [user, setUser] = useState<User | null>(null)
  const [schedules, setSchedules] = useState<Schedule[]>([])
  const [statusMessage, setStatusMessage] = useState<string>('')
  const [errorMessage, setErrorMessage] = useState<string>('')
  const [syncToastMessage, setSyncToastMessage] = useState<string>('')
  const [isBusy, setIsBusy] = useState<boolean>(false)
  const [isCreateEventOpen, setIsCreateEventOpen] = useState<boolean>(false)
  // Tracks the pre-filled start/end for when user clicks on the calendar
  const [createEventInitialTimes, setCreateEventInitialTimes] = useState<{ startDate: string; endDate: string } | null>(null)
  const [isWorkspaceSidebarCollapsed, setIsWorkspaceSidebarCollapsed] = useState<boolean>(false)
  const [activeWorkspaceView, setActiveWorkspaceView] = useState<'home' | 'note' | 'record' | 'settings'>('home')
  const [activeWorkspaceNoteId, setActiveWorkspaceNoteId] = useState<string | null>(null)
  const [googleCalendarStatus, setGoogleCalendarStatus] = useState<GoogleCalendarStatus | null>(null)

  // Collapsible sidebar sections state
  const [sectionNoteOpen, setSectionNoteOpen] = useState(true)
  const [sectionRecordOpen, setSectionRecordOpen] = useState(true)

  const weekRange = useMemo(() => getRangeForCurrentWeek(), [])
  const [startDate, setStartDate] = useState<string>(weekRange.startDate)
  const [endDate, setEndDate] = useState<string>(weekRange.endDate)

  const [recentNotes, setRecentNotes] = useState<AppNote[]>([])
  const recentNotesRef = useRef<AppNote[]>([])
  const noteSyncTimersRef = useRef<Record<string, number>>({})
  const syncToastTimerRef = useRef<number | null>(null)

  const [notifications, setNotifications] = useState<AppNotification[]>([])

  useEffect(() => {
    recentNotesRef.current = recentNotes
  }, [recentNotes])

  const handleNoteChange = useCallback((id: string, contentMd: string) => {
    setRecentNotes((prev) => prev.map((n) => (n.id === id ? { ...n, contentMd } : n)))
    scheduleNotePersist(id)
  }, [])

  const noteSummaries = useMemo(
    () => recentNotes.map((note) => ({ id: note.id, date: note.date, title: noteTitleFromMd(note.contentMd) })),
    [recentNotes],
  )
  const activeWorkspaceNote = useMemo(
    () => recentNotes.find((note) => note.id === activeWorkspaceNoteId) ?? null,
    [recentNotes, activeWorkspaceNoteId],
  )

  const openWorkspaceNote = useCallback((noteId: string) => {
    setActiveWorkspaceNoteId(noteId)
    setActiveWorkspaceView('note')
  }, [])

  useEffect(() => { writeStoredTokens(tokens) }, [tokens])

  useEffect(() => {
    if (!recentNotes.length || activeWorkspaceNoteId) return
    setActiveWorkspaceNoteId(recentNotes[0].id)
  }, [recentNotes, activeWorkspaceNoteId])

  useEffect(() => {
    if (!tokens) {
      setUser(null)
      setSchedules([])
      setRecentNotes([])
      setActiveWorkspaceNoteId(null)
      setGoogleCalendarStatus(null)
      return
    }
    void fetchCurrentUser(tokens)
    void fetchSchedules(tokens)
    void fetchGoogleCalendarStatus()
  }, [tokens, startDate, endDate])

  useEffect(() => {
    if (!tokens) return
    void fetchNotes(tokens)
  }, [tokens])

  useEffect(() => {
    const url = new URL(window.location.href)
    const result = url.searchParams.get('google_calendar')
    const reason = url.searchParams.get('reason')
    if (!result) return

    if (result === 'connected') {
      setStatusMessage('Google Calendar connected successfully.')
    } else if (result === 'error') {
      setErrorMessage(reason ? `Google connection failed: ${reason}` : 'Google connection failed')
    }

    url.searchParams.delete('google_calendar')
    url.searchParams.delete('reason')
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}`)
  }, [])

  useEffect(
    () => () => {
      Object.values(noteSyncTimersRef.current).forEach((timerId) => window.clearTimeout(timerId))
      noteSyncTimersRef.current = {}
      if (syncToastTimerRef.current) {
        window.clearTimeout(syncToastTimerRef.current)
        syncToastTimerRef.current = null
      }
    },
    [],
  )

  function showSyncToast(message: string): void {
    setSyncToastMessage(message)
    // Thêm notification
    const newNotif: AppNotification = {
      id: Date.now().toString(),
      kind: 'sync',
      title: 'Calendar synced',
      body: message,
      timestamp: new Date(),
      read: false,
    }
    setNotifications((prev) => [newNotif, ...prev].slice(0, 50))
    if (syncToastTimerRef.current) {
      window.clearTimeout(syncToastTimerRef.current)
    }
    syncToastTimerRef.current = window.setTimeout(() => {
      setSyncToastMessage('')
      syncToastTimerRef.current = null
    }, 5000)
  }

  function formatSyncSummary(event: SyncUpdateEvent): string {
    const created = event.stats.created ?? 0
    const updated = event.stats.updated ?? 0
    const deleted = event.stats.deleted ?? 0
    const skipped = event.stats.skipped ?? 0
    const source = event.source === 'google_calendar' ? 'Google Calendar' : event.source
    return `${source} sync: +${created} / ~${updated} / -${deleted} (skip ${skipped})`
  }

  async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
    const response = await fetch(url, init)
    const text = await response.text()
    const body = text ? JSON.parse(text) : null
    if (!response.ok) throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status)
    return body as T
  }

  async function refreshToken(currentRefreshToken: string): Promise<TokenPair> {
    const payload = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(
      `${API_BASE_URL}/auth/refresh`,
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: currentRefreshToken }) },
    )
    return { accessToken: payload.access_token, refreshToken: payload.refresh_token }
  }

  async function requestWithAuth<T>(path: string, init?: RequestInit): Promise<T> {
    if (!tokens) throw new Error('Please login first')
    const headers = new Headers(init?.headers ?? {})
    headers.set('Authorization', `Bearer ${tokens.accessToken}`)
    let response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers })
    if (response.status === 401) {
      const newTokens = await refreshToken(tokens.refreshToken)
      setTokens(newTokens)
      const retryHeaders = new Headers(init?.headers ?? {})
      retryHeaders.set('Authorization', `Bearer ${newTokens.accessToken}`)
      response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: retryHeaders })
    }
    const text = await response.text()
    const body = text ? JSON.parse(text) : null
    if (!response.ok) throw new ApiError(body?.detail ?? `Request failed (${response.status})`, response.status)
    return body as T
  }

  async function fetchNotes(activeTokens?: TokenPair): Promise<void> {
    const sessionTokens = activeTokens ?? tokens
    if (!sessionTokens) return
    try {
      const data = await requestWithAuth<ApiNote[]>('/notes')
      setRecentNotes(data.map(mapApiNoteToAppNote))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot load notes')
    }
  }

  async function persistNoteContent(noteId: string): Promise<void> {
    const target = recentNotesRef.current.find((note) => note.id === noteId)
    if (!target) return
    try {
      const payload: { version: number; content?: string } = { version: target.version }
      // Only include content if it's not empty
      if (target.contentMd.trim()) {
        payload.content = target.contentMd
      }
      const updated = await requestWithAuth<ApiNote>(`/notes/${noteId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const mapped = mapApiNoteToAppNote(updated)
      setRecentNotes((prev) => prev.map((note) => (note.id === noteId ? { ...note, ...mapped } : note)))
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setErrorMessage('Note update conflict. Reloaded latest note version.')
        await fetchNotes()
        return
      }
      setErrorMessage(error instanceof Error ? error.message : 'Cannot save note')
    }
  }

  function scheduleNotePersist(noteId: string): void {
    const existing = noteSyncTimersRef.current[noteId]
    if (existing) window.clearTimeout(existing)
    noteSyncTimersRef.current[noteId] = window.setTimeout(() => {
      void persistNoteContent(noteId)
      delete noteSyncTimersRef.current[noteId]
    }, 280)
  }

  async function handleCreateNote(): Promise<void> {
    setErrorMessage('')
    try {
      const created = await requestWithAuth<ApiNote>('/notes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: '# New note',
          content_type: 'markdown',
          position: { x: 0, y: 0 },
          size: { width: 200, height: 200 },
          style: { color: 'yellow' },
        }),
      })
      const mapped = mapApiNoteToAppNote(created)
      setRecentNotes((prev) => [mapped, ...prev])
      openWorkspaceNote(mapped.id)
      setStatusMessage('Note created.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot create note')
    }
  }

  async function handleDeleteNote(noteId: string): Promise<void> {
    setErrorMessage('')
    try {
      await requestWithAuth<void>(`/notes/${noteId}`, { method: 'DELETE' })
      setRecentNotes((prev) => prev.filter((n) => n.id !== noteId))
      if (activeWorkspaceNoteId === noteId) {
        const remaining = recentNotesRef.current.filter((n) => n.id !== noteId)
        setActiveWorkspaceNoteId(remaining[0]?.id ?? null)
        if (activeWorkspaceView === 'note') setActiveWorkspaceView('home')
      }
      setStatusMessage('Note deleted.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot delete note')
    }
  }

  async function fetchCurrentUser(activeTokens: TokenPair): Promise<void> {
    try {
      const profile = await fetch(`${API_BASE_URL}/auth/me`, { headers: { Authorization: `Bearer ${activeTokens.accessToken}` } })
      if (profile.status === 401) {
        const nextTokens = await refreshToken(activeTokens.refreshToken)
        setTokens(nextTokens)
        const retried = await fetch(`${API_BASE_URL}/auth/me`, { headers: { Authorization: `Bearer ${nextTokens.accessToken}` } })
        if (!retried.ok) throw new Error('Cannot load profile')
        setUser((await retried.json()) as User)
        return
      }
      if (!profile.ok) throw new Error('Cannot load profile')
      setUser((await profile.json()) as User)
    } catch {
      setTokens(null); setUser(null)
      setErrorMessage('Your session expired. Please login again.')
    }
  }

  async function handleRegister(name: string, email: string, pass: string): Promise<void> {
    setErrorMessage(''); setStatusMessage(''); setIsBusy(true)
    try {
      await requestJson<User>(`${API_BASE_URL}/auth/register`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pass, full_name: name }),
      })
      setStatusMessage('Account created. You can login now.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Register failed')
    } finally { setIsBusy(false) }
  }

  async function handleLogin(email: string, pass: string): Promise<void> {
    setErrorMessage(''); setStatusMessage(''); setIsBusy(true)
    try {
      const codeVerifier = randomUrlSafeString(64).slice(0, 96)
      const codeChallenge = await createCodeChallenge(codeVerifier)
      const authorize = await requestJson<{ code: string }>(`${API_BASE_URL}/auth/authorize`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pass, client_id: PKCE_CLIENT_ID, redirect_uri: PKCE_REDIRECT_URI, code_challenge: codeChallenge, code_challenge_method: 'S256', state: randomUrlSafeString(24) }),
      })
      const tokenPair = await requestJson<{ access_token: string; refresh_token: string; token_type: string }>(`${API_BASE_URL}/auth/token`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: authorize.code, code_verifier: codeVerifier, client_id: PKCE_CLIENT_ID, redirect_uri: PKCE_REDIRECT_URI }),
      })
      setTokens({ accessToken: tokenPair.access_token, refreshToken: tokenPair.refresh_token })
      setStatusMessage('Login successful.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Login failed')
    } finally { setIsBusy(false) }
  }

  async function fetchSchedules(activeTokens?: TokenPair): Promise<void> {
    const sessionTokens = activeTokens ?? tokens
    if (!sessionTokens) return
    try {
      const data = await requestWithAuth<ScheduleListResponse>(`/schedules?start_date=${encodeURIComponent(toIsoDateTime(startDate))}&end_date=${encodeURIComponent(toIsoDateTime(endDate))}`)
      setSchedules(data.items)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot load schedules')
    }
  }

  async function fetchGoogleCalendarStatus(): Promise<void> {
    if (!tokens) return
    try {
      const status = await requestWithAuth<GoogleCalendarStatus>('/google-calendar/status')
      setGoogleCalendarStatus(status)
    } catch (error) {
      setGoogleCalendarStatus(null)
      setErrorMessage(error instanceof Error ? error.message : 'Cannot load Google Calendar status')
    }
  }

  async function handleConnectGoogleCalendar(): Promise<void> {
    setErrorMessage('')
    try {
      const payload = await requestWithAuth<{ authorization_url: string }>('/google-calendar/connect-url')
      window.location.href = payload.authorization_url
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot connect Google Calendar')
    }
  }

  async function handleDisconnectGoogleCalendar(): Promise<void> {
    setErrorMessage('')
    try {
      await requestWithAuth<{ message: string }>('/google-calendar/disconnect', { method: 'DELETE' })
      setGoogleCalendarStatus({
        connected: false,
        provider: 'GOOGLE',
        calendar_id: null,
        granted_scopes: [],
        last_synced_at: null,
        has_sync_token: false,
        channel_expiration: null,
        last_sync_error: null,
      })
      setStatusMessage('Google Calendar disconnected.')
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot disconnect Google Calendar')
    }
  }

  async function handleSyncGoogleCalendarNow(): Promise<void> {
    setErrorMessage('')
    try {
      const resp = await requestWithAuth<{ message: string }>('/google-calendar/sync-now', { method: 'POST' })
      setStatusMessage(resp.message)
      await fetchGoogleCalendarStatus()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot sync Google Calendar')
    }
  }

  async function handleCreateSchedule(schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>): Promise<void> {
    setErrorMessage(''); setStatusMessage('')
    try {
      await requestWithAuth<Schedule>('/schedules', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(schedule) })
      setStatusMessage('Schedule created.')
      await fetchSchedules()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Cannot create schedule')
    }
  }

  async function handleToggleComplete(item: Schedule): Promise<void> {
    try {
      await requestWithAuth<Schedule>(`/schedules/${item.id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_completed: !item.is_completed }) })
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
    if (!tokens) return
    try {
      await requestJson<{ message: string }>(`${API_BASE_URL}/auth/logout`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokens.refreshToken }),
      })
    } catch { /* continue */ }
    setTokens(null); setUser(null); setSchedules([])
    setStatusMessage('You are logged out.')
  }

  // New feature: open create event modal with pre-filled times from calendar click
  const handleCalendarSlotSelect = useCallback((slotStart: Date, slotEnd: Date) => {
    setCreateEventInitialTimes({
      startDate: toLocalInputDateTime(slotStart),
      endDate: toLocalInputDateTime(slotEnd),
    })
    setIsCreateEventOpen(true)
  }, [])

  const handleOpenCreateEvent = useCallback(() => {
    setCreateEventInitialTimes(null) // will use current time defaults inside ScheduleForm
    setIsCreateEventOpen(true)
  }, [])

  const handleCloseCreateEvent = useCallback(() => {
    setIsCreateEventOpen(false)
    setCreateEventInitialTimes(null)
  }, [])

  useEffect(() => {
    if (!tokens?.accessToken) return

    const abortController = new AbortController()
    let isStopped = false

    const sleep = (ms: number) => new Promise((resolve) => {
      window.setTimeout(resolve, ms)
    })

    const processSseChunk = (chunk: string): void => {
      const lines = chunk.split('\n')
      const dataLines: string[] = []
      for (const line of lines) {
        if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trimStart())
        }
      }
      if (!dataLines.length) return
      const rawData = dataLines.join('\n').trim()
      if (!rawData || rawData === 'ping') return

      try {
        const payload = JSON.parse(rawData) as SyncUpdateEvent
        if (payload.event !== 'sync.update') return
        showSyncToast(formatSyncSummary(payload))
        void fetchSchedules()
        void fetchGoogleCalendarStatus()
      } catch {
        // Ignore malformed SSE payloads.
      }
    }

    const connect = async () => {
      const tabAppId = getOrCreateSseTabAppId()
      const sseUrl = `${API_BASE_URL}/sse/sync/events?appid=${encodeURIComponent(tabAppId)}`
      let retryDelayMs = 3000
      const maxRetryDelayMs = 30000

      while (!isStopped) {
        try {
          const response = await fetch(sseUrl, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: 'text/event-stream',
            },
            signal: abortController.signal,
          })

          if (!response.ok || !response.body) {
            throw new Error(`SSE request failed (${response.status})`)
          }

          retryDelayMs = 3000

          const reader = response.body.getReader()
          const decoder = new TextDecoder('utf-8')
          let buffer = ''

          while (!isStopped) {
            const { value, done } = await reader.read()
            if (done) break

            buffer += decoder.decode(value, { stream: true })
            let splitIndex = buffer.indexOf('\n\n')
            while (splitIndex !== -1) {
              const chunk = buffer.slice(0, splitIndex)
              buffer = buffer.slice(splitIndex + 2)
              processSseChunk(chunk)
              splitIndex = buffer.indexOf('\n\n')
            }
          }
        } catch {
          if (isStopped) break
          await sleep(retryDelayMs)
          retryDelayMs = Math.min(retryDelayMs * 2, maxRetryDelayMs)
        }
      }
    }

    void connect()

    return () => {
      isStopped = true
      abortController.abort()
    }
  }, [tokens?.accessToken])

  const userInitial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? '?'

  return (
    <div className="app-shell">
      {/* TOP BAR */}
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand-logo">
            <div className="brand-icon">C</div>
            <span className="brand-name">Cortex</span>
          </div>
          {tokens && (
            <>
              <div className="topbar-divider" />
              <nav className="breadcrumb">
                <span className="breadcrumb-item">Workspace</span>
                <span className="breadcrumb-sep">/</span>
                <span className="breadcrumb-item" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                  {activeWorkspaceView === 'home' ? 'Home'
                    : activeWorkspaceView === 'record' ? 'Record'
                      : activeWorkspaceView === 'settings' ? 'Settings'
                        : (activeWorkspaceNote ? noteTitleFromMd(activeWorkspaceNote.contentMd) : 'Note')}
                </span>
              </nav>
            </>
          )}
        </div>

        <div className="topbar-right">
          {tokens && (
            <>
              <NotificationBell
                notifications={notifications}
                onMarkRead={(id) => setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))}
                onMarkAllRead={() => setNotifications(prev => prev.map(n => ({ ...n, read: true })))}
                onDismiss={(id) => setNotifications(prev => prev.filter(n => n.id !== id))}
              />
              <div className="user-avatar" title={user?.email}>{userInitial}</div>
              <button type="button" className="topbar-btn" onClick={handleLogout} title="Logout">
                <LogOut size={13} />
              </button>
            </>
          )}
        </div>
      </header>

      {/* STATUS BAR */}
      {statusMessage && !errorMessage && (
        <div className="status-bar ok">
          <CheckCircle2 size={14} />
          <span>{statusMessage}</span>
        </div>
      )}
      {errorMessage && (
        <div className="status-bar error">
          <AlertCircle size={14} />
          <span>{errorMessage}</span>
        </div>
      )}
      {!errorMessage && syncToastMessage && (
        <div className="status-bar ok">
          <CheckCircle2 size={14} />
          <span>{syncToastMessage}</span>
        </div>
      )}

      {/* MAIN CONTENT */}
      {!tokens ? (
        <div className="main-layout">
          <AuthPanel onLogin={handleLogin} onRegister={handleRegister} isBusy={isBusy} />
        </div>
      ) : (
        <div className="main-layout">
          <aside className={`workspace-sidebar ${isWorkspaceSidebarCollapsed ? 'collapsed' : ''}`}>
            <button
              type="button"
              className="workspace-sidebar-toggle"
              onClick={() => setIsWorkspaceSidebarCollapsed((prev) => !prev)}
              aria-label={isWorkspaceSidebarCollapsed ? 'Mở sidebar' : 'Thu sidebar'}
            >
              {isWorkspaceSidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
            </button>

            <div className="workspace-sidebar-body">
              <div className="workspace-sidebar-main">
                {/* Home nav item */}
                <button
                  type="button"
                  className={`workspace-nav-item ${activeWorkspaceView === 'home' ? 'active' : ''}`}
                  onClick={() => setActiveWorkspaceView('home')}
                >
                  <Home size={15} />
                  <span>Home</span>
                </button>

                {/* Notes section — collapsible */}
                <SidebarSection
                  icon={<StickyNote size={14} />}
                  label="Notes"
                  isOpen={sectionNoteOpen}
                  onToggle={() => setSectionNoteOpen(v => !v)}
                  isCollapsed={isWorkspaceSidebarCollapsed}
                >
                  <div className="workspace-note-links">
                    {noteSummaries.map((note) => (
                      <button
                        key={note.id}
                        type="button"
                        className={`workspace-nav-item workspace-nav-item--sub ${activeWorkspaceView === 'note' && activeWorkspaceNoteId === note.id ? 'active' : ''}`}
                        onClick={() => openWorkspaceNote(note.id)}
                        title={note.title}
                      >
                        <StickyNote size={13} />
                        <span>{note.title}</span>
                      </button>
                    ))}
                    <button
                      type="button"
                      className="workspace-nav-item workspace-nav-item--sub workspace-nav-item--add"
                      onClick={handleCreateNote}
                      title="New note"
                    >
                      <Plus size={13} />
                      <span>New note</span>
                    </button>
                  </div>
                </SidebarSection>

                {/* Record section — collapsible */}
                <SidebarSection
                  icon={<Video size={14} />}
                  label="Record"
                  isOpen={sectionRecordOpen}
                  onToggle={() => {
                    setSectionRecordOpen(v => !v)
                    if (!sectionRecordOpen) setActiveWorkspaceView('record')
                  }}
                  isCollapsed={isWorkspaceSidebarCollapsed}
                >
                  <button
                    type="button"
                    className={`workspace-nav-item workspace-nav-item--sub ${activeWorkspaceView === 'record' ? 'active' : ''}`}
                    onClick={() => setActiveWorkspaceView('record')}
                  >
                    <Video size={13} />
                    <span>Open recorder</span>
                  </button>
                </SidebarSection>
              </div>

              <div className="workspace-sidebar-footer">
                <button
                  type="button"
                  className={`workspace-nav-item ${activeWorkspaceView === 'settings' ? 'active' : ''}`}
                  onClick={() => setActiveWorkspaceView('settings')}
                >
                  <Settings size={15} />
                  <span>Settings</span>
                </button>
              </div>
            </div>
          </aside>

          <div className="workspace-area">
            {activeWorkspaceView === 'home' ? (
              <section className="home-workspace">
                <div className="home-schedule-area">
                  <CalendarView
                    schedules={schedules}
                    isGoogleCalendarConnected={Boolean(googleCalendarStatus?.connected)}
                    startDate={startDate}
                    endDate={endDate}
                    onStartDateChange={setStartDate}
                    onEndDateChange={setEndDate}
                    onFetch={() => fetchSchedules()}
                    onOpenCreateEvent={handleOpenCreateEvent}
                    onSlotSelect={handleCalendarSlotSelect}
                    onToggleComplete={handleToggleComplete}
                    onRemove={handleRemoveSchedule}
                  />
                </div>
                <div className="home-quick-notes-area">
                  <NoteSidebar
                    notes={recentNotes}
                    onNoteChange={handleNoteChange}
                    onCreateNote={handleCreateNote}
                    onDeleteNote={handleDeleteNote}
                  />
                </div>
              </section>
            ) : activeWorkspaceView === 'record' ? (
              <div >
              </div>
            ) : activeWorkspaceView === 'settings' ? (
              <section className="settings-workspace">
                <div className="settings-workspace-header">
                  <h1 className="page-title">Settings</h1>
                </div>
                <div className="settings-card">
                  <div className="settings-card-title">Google Calendar</div>
                  <div className="settings-card-subtitle">
                    Manage connection and manual sync for your calendar integration.
                  </div>
                  <div className="settings-actions-row">
                    {!googleCalendarStatus?.connected ? (
                      <button type="button" className="btn btn-primary" onClick={handleConnectGoogleCalendar}>
                        Connect Google
                      </button>
                    ) : (
                      <>
                        <button type="button" className="btn btn-ghost" onClick={handleSyncGoogleCalendarNow}>
                          Sync Google
                        </button>
                        <button type="button" className="btn btn-danger" onClick={handleDisconnectGoogleCalendar}>
                          Disconnect Google
                        </button>
                      </>
                    )}
                  </div>
                  <div className="settings-meta-list">
                    <div>Status: {googleCalendarStatus?.connected ? 'Connected' : 'Not connected'}</div>
                    <div>Last sync: {formatDateTimeVi(googleCalendarStatus?.last_synced_at ?? null)}</div>
                    <div>Channel expires: {formatDateTimeVi(googleCalendarStatus?.channel_expiration ?? null)}</div>
                    {googleCalendarStatus?.last_sync_error && (
                      <div className="settings-meta-error">Last error: {googleCalendarStatus.last_sync_error}</div>
                    )}
                  </div>
                </div>
              </section>
            ) : activeWorkspaceNote ? (
              <div className="workspace-note-page">
                <WorkspaceNoteEditor note={activeWorkspaceNote} onChange={handleNoteChange} />
              </div>
            ) : (
              <section className="workspace-empty-note">
                <p>Chọn một note từ sidebar để mở trong workspace.</p>
              </section>
            )}

            <RecordPanel requestWithAuth={requestWithAuth} isVisible={activeWorkspaceView === 'record'} />
          </div>
        </div>
      )}

      {/* CREATE EVENT MODAL */}
      {tokens && isCreateEventOpen && (
        <div className="modal-backdrop" onClick={handleCloseCreateEvent}>
          <div className="modal create-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <div className="modal-title-area">
                <div className="modal-title">New event</div>
              </div>
              <button type="button" className="modal-close" onClick={handleCloseCreateEvent}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body">
              <ScheduleForm
                onCreate={handleCreateSchedule}
                weekRange={weekRange}
                initialTimes={createEventInitialTimes}
                onClose={handleCloseCreateEvent}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App