import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, GitBranch, Home, Plus, Search, Settings, StickyNote, Video, X, Trash2 } from 'lucide-react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import './App.css'
import './styles/settings.css'
import './styles/globalHome.css'
import './styles/workspace-settings.css'
import { AuthPanel } from './components/AuthPanel'
import { ScheduleForm } from './components/ScheduleForm'
import { CalendarView } from './components/CalendarView'
import { RecordPanel } from './components/RecordPanel'
import { AssetKnowledgeView } from './components/AssetKnowledgeView'
import { SettingsPanel } from './components/SettingsPanel'
import type { SyncUpdateEvent } from './types'
import type { AppNotification } from './components/NotificationBell'
import { NotificationBell } from './components/NotificationBell'
import type { NotificationKind } from './components/NotificationBell'
import { WorkspaceNoteEditor } from './components/WorkspaceNoteEditor'
import { WorkspaceSearch } from './components/WorkspaceSearch'
import { WorkspaceSwitcher } from './components/WorkspaceSwitcher'
import { WorkspaceCreateModal } from './components/WorkspaceCreateModal'
import { WorkspaceMembersModal } from './components/WorkspaceMembersModal'
import { WorkspaceSettingsModal } from './components/WorkspaceSettingsModal'
import { GlobalHome } from './components/GlobalHome'
import { AskAI } from './components/AskAI'
import { WorkflowBuilder } from './components/WorkflowBuilder'
import { getStoredTheme, applyThemeToDocument } from './utils/theme'
import type { AppTheme } from './utils/theme'
import { getBlockEditingEnabled, setBlockEditingEnabled } from './utils/noteSettings'
import { useAuth } from './hooks/useAuth'
import { useWorkspaces } from './hooks/useWorkspaces'
import { useNotes, noteTitleFromMd } from './hooks/useNotes'
import { useSchedules } from './hooks/useSchedules'
import { useAssets } from './hooks/useAssets'
import { useNotifications } from './hooks/useNotifications'
import { requestWithAuth, getCurrentTokens, setCurrentTokens } from './services/api'
import { extractWorkspaceId, isWorkspaceRoute, noteRoute, knowledgeRoute, scheduleRoute, workspaceRoute, workflowRoute } from './services/routes'
import type { Workspace } from './types'

const SSE_TAB_APPID_KEY = 'cortex_sse_appid'

type WorkspaceView = 'dashboard' | 'note' | 'records' | 'knowledge' | 'schedule' | 'settings' | 'workflow'

function getRouteWorkspaceState(pathname: string): {
  view: WorkspaceView
  workspaceId: string | null
  noteId: string | null
  assetId: string | null
  workflowId: string | null
} {
  if (matchPath('/schedule', pathname)) {
    return { view: 'schedule', workspaceId: null, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/w/:workspaceId/schedule', pathname)) {
    const wsId = extractWorkspaceId(pathname)
    return { view: 'schedule', workspaceId: wsId, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/settings', pathname)) {
    return { view: 'settings', workspaceId: null, noteId: null, assetId: null, workflowId: null }
  }

  const workspaceId = extractWorkspaceId(pathname)

  if (workspaceId) {
    const workflowMatch = matchPath('/w/:workspaceId/workflows/:workflowId', pathname)
    if (workflowMatch?.params.workflowId) {
      return {
        view: 'workflow',
        workspaceId,
        noteId: null,
        assetId: null,
        workflowId: workflowMatch.params.workflowId
      }
    }

    if (matchPath('/w/:workspaceId/workflows', pathname)) {
      return { view: 'workflow', workspaceId, noteId: null, assetId: null, workflowId: null }
    }

    const knowledgeMatch = matchPath('/w/:workspaceId/records/:assetId/knowledge', pathname)
    if (knowledgeMatch?.params.assetId) {
      return {
        view: 'knowledge',
        workspaceId,
        noteId: null,
        assetId: knowledgeMatch.params.assetId,
        workflowId: null
      }
    }

    const noteMatch = matchPath('/w/:workspaceId/notes/:noteId', pathname)
    if (noteMatch?.params.noteId) {
      return {
        view: 'note',
        workspaceId,
        noteId: noteMatch.params.noteId,
        assetId: null,
        workflowId: null
      }
    }

    if (matchPath('/w/:workspaceId/records', pathname)) {
      return { view: 'records', workspaceId, noteId: null, assetId: null, workflowId: null }
    }

    if (matchPath('/w/:workspaceId', pathname) || matchPath('/w/:workspaceId/notes', pathname)) {
      return { view: 'dashboard', workspaceId, noteId: null, assetId: null, workflowId: null }
    }
  }

  return { view: 'dashboard', workspaceId: null, noteId: null, assetId: null, workflowId: null }
}

function isKnownRoute(pathname: string): boolean {
  return pathname === '/'
    || pathname === '/schedule'
    || pathname === '/settings'
    || pathname === '/notifications'
    || pathname === '/auth/callback'
    || isWorkspaceRoute(pathname)
}

function getOrCreateSseTabAppId(): string {
  const existing = window.sessionStorage.getItem(SSE_TAB_APPID_KEY)
  if (existing) return existing

  const rand = Math.random().toString(36).slice(2, 10)
  const appid = `frontend-${rand}`
  window.sessionStorage.setItem(SSE_TAB_APPID_KEY, appid)
  return appid
}

function SidebarSection({
  icon,
  label,
  isOpen,
  onToggle,
  isCollapsed,
  sectionBodyProps,
  children,
  onLabelClick,
}: {
  icon: React.ReactNode
  label: string
  isOpen: boolean
  onToggle: () => void
  isCollapsed: boolean
  sectionBodyProps?: React.HTMLAttributes<HTMLDivElement>
  children?: React.ReactNode
  onLabelClick?: () => void
}) {
  const { className: sectionBodyClassName, ...sectionBodyRestProps } = sectionBodyProps ?? {}

  return (
    <div className="sidebar-collapsible-section">
      <button
        type="button"
        className="app-sidebar-section-header"
        onClick={onToggle}
        aria-expanded={isOpen}
        title={label}
      >
        <span className="app-sidebar-section-header-icon">{icon}</span>
        {!isCollapsed && (
          <>
            <span
              className="app-sidebar-section-header-label"
              onClick={(e) => {
                if (onLabelClick) {
                  e.stopPropagation()
                  onLabelClick()
                }
              }}
              style={onLabelClick ? { cursor: 'pointer' } : undefined}
            >
              {label}
            </span>
            <span className={`app-sidebar-section-chevron ${isOpen ? 'open' : ''}`}>
              <ChevronDown size={13} />
            </span>
          </>
        )}
      </button>
      {isOpen && !isCollapsed && (
        <div
          className={[
            'app-sidebar-section-body',
            sectionBodyClassName ?? '',
          ].filter(Boolean).join(' ')}
          {...sectionBodyRestProps}
        >
          {children}
        </div>
      )}
    </div>
  )
}

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const routeWorkspaceState = useMemo(() => getRouteWorkspaceState(location.pathname), [location.pathname])

  const auth = useAuth()
  const workspaces = useWorkspaces()
  const notes = useNotes(workspaces.currentWorkspace, routeWorkspaceState.noteId)
  const schedules = useSchedules()
  const assets = useAssets(workspaces.currentWorkspace)

  const [isCreateEventOpen, setIsCreateEventOpen] = useState<boolean>(false)
  const [isSearchOpen, setIsSearchOpen] = useState(false)
  const [isAskAIOpen, setIsAskAIOpen] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('cortex_askai_open')
      return saved ? JSON.parse(saved) : false
    } catch {
      return false
    }
  })
  const [pendingSelection, setPendingSelection] = useState<string>('')
  const [isCreateWorkspaceOpen, setIsCreateWorkspaceOpen] = useState(false)
  const [managingMembersWorkspace, setManagingMembersWorkspace] = useState<{ id: string; name: string; is_personal: boolean } | null>(null)
  const [settingsWorkspace, setSettingsWorkspace] = useState<Workspace | null>(null)
  const [createEventInitialTimes, setCreateEventInitialTimes] = useState<{ startDate: string; endDate: string } | null>(null)
  const isWorkspaceSidebarCollapsed = false
   const [theme, _setTheme] = useState<AppTheme>(getStoredTheme)
   const [blockEditingEnabled, _setBlockEditingEnabled] = useState<boolean>(getBlockEditingEnabled)
   const [sectionNoteOpen, setSectionNoteOpen] = useState(true)
   const [sectionRecordOpen, setSectionRecordOpen] = useState(true)
   const notif = useNotifications()
   const syncToastTimerRef = useRef<number | null>(null)

  const activeWorkspaceView = routeWorkspaceState.view
  const [activeWorkspaceAssetId, setActiveWorkspaceAssetId] = useState<string | null>(routeWorkspaceState.assetId)
  const [activeWorkspaceKnowledgeAssetId, setActiveWorkspaceKnowledgeAssetId] = useState<string | null>(routeWorkspaceState.assetId)
  const [activeWorkspaceWorkflowId, setActiveWorkspaceWorkflowId] = useState<string | null>(routeWorkspaceState.workflowId)

useEffect(() => {
     setActiveWorkspaceAssetId(routeWorkspaceState.assetId)
     setActiveWorkspaceWorkflowId(routeWorkspaceState.workflowId)
     if (routeWorkspaceState.view === 'knowledge') {
       setActiveWorkspaceKnowledgeAssetId(routeWorkspaceState.assetId)
     }
   }, [routeWorkspaceState.assetId, routeWorkspaceState.view, routeWorkspaceState.workflowId])

  useEffect(() => {
    applyThemeToDocument(theme)
    window.localStorage.setItem('cortex_theme', theme)
  }, [theme])

  useEffect(() => {
    window.localStorage.setItem('cortex_askai_open', JSON.stringify(isAskAIOpen))
  }, [isAskAIOpen])

  useEffect(() => {
    if (isKnownRoute(location.pathname)) return
    navigate('/', { replace: true })
  }, [location.pathname, navigate])

  useEffect(() => {
    if (matchPath('/w/:workspaceId', location.pathname) || matchPath('/w/:workspaceId/schedule', location.pathname)) {
      navigate(scheduleRoute(), { replace: true })
    }
  }, [location.pathname, navigate])

  useEffect(() => {
    if (!('Notification' in window) || Notification.permission !== 'default') return
    const handler = () => {
      Notification.requestPermission()
      document.removeEventListener('click', handler)
    }
    document.addEventListener('click', handler, { once: true })
    return () => document.removeEventListener('click', handler)
  }, [])

useEffect(() => {
     if (!sectionRecordOpen || !auth.tokens || !workspaces.currentWorkspace) return
     void assets.loadSidebarAssets()
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [sectionRecordOpen, auth.tokens, workspaces.currentWorkspace])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setIsSearchOpen(prev => !prev)
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])

useEffect(() => {
     if (!auth.tokens) {
       workspaces.setCurrentWorkspace(null)
       return
     }
     void workspaces.fetchWorkspaces()
     void schedules.fetchSchedules()
     void schedules.fetchGoogleCalendarStatus()
     void notif.fetchNotifications()
     // Request browser notification permission
     if ('Notification' in window && Notification.permission === 'default') {
       void Notification.requestPermission()
     }
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens])

useEffect(() => {
     if (!routeWorkspaceState.workspaceId || workspaces.workspaces.length === 0) return

     const targetWorkspace = workspaces.workspaces.find(ws => ws.id === routeWorkspaceState.workspaceId)
     if (targetWorkspace && targetWorkspace.id !== workspaces.currentWorkspace?.id) {
       workspaces.setCurrentWorkspace(targetWorkspace)
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [routeWorkspaceState.workspaceId, workspaces.workspaces.length, workspaces.workspaces])

useEffect(() => {
     if (!auth.tokens) return
     void notes.fetchNotes()
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens, workspaces.currentWorkspace?.id])

  useEffect(() => {
    const url = new URL(window.location.href)
    const result = url.searchParams.get('google_calendar')
    const reason = url.searchParams.get('reason')
    if (!result) return

    if (result === 'connected') {
      auth.setStatusMessage('Google Calendar connected successfully.')
    } else if (result === 'error') {
      auth.setErrorMessage(reason ? `Google connection failed: ${reason}` : 'Google connection failed')
    }

    url.searchParams.delete('google_calendar')
    url.searchParams.delete('reason')
    window.history.replaceState({}, document.title, `${url.pathname}${url.search}`)
  }, [auth])

const showSyncToast = useCallback((message: string): void => {
     auth.setStatusMessage(message)
     const newNotif: AppNotification = {
       id: Date.now().toString(),
       kind: 'sync',
       title: 'Calendar synced',
       body: message,
       timestamp: new Date(),
       read: false,
     }
     notif.addNotification(newNotif)
     if (syncToastTimerRef.current) {
       window.clearTimeout(syncToastTimerRef.current)
     }
     syncToastTimerRef.current = window.setTimeout(() => {
       auth.setStatusMessage('')
       syncToastTimerRef.current = null
     }, 5000)
   }, [auth, notif])

   function formatSyncSummary(event: SyncUpdateEvent): string {
    const created = event.stats.created ?? 0
    const updated = event.stats.updated ?? 0
    const deleted = event.stats.deleted ?? 0
    const skipped = event.stats.skipped ?? 0
    const source = event.source === 'google_calendar' ? 'Google Calendar' : event.source
    return `${source} sync: +${created} / ~${updated} / -${deleted} (skip ${skipped})`
  }

  const handleWorkspaceSwitch = useCallback((workspace: typeof workspaces.currentWorkspace): void => {
    if (!workspace || workspace.id === workspaces.currentWorkspace?.id) return

    notes.clearNotes()
    workspaces.switchWorkspace(workspace)
    navigate(workspaceRoute(workspace.id), { replace: true })
  }, [navigate, notes, workspaces])

  const openWorkspaceNote = useCallback((noteId: string) => {
    const workspaceId = workspaces.currentWorkspace?.id
    if (workspaceId) {
      navigate(noteRoute(workspaceId, noteId))
    }
  }, [navigate, workspaces.currentWorkspace])

  const handleCreateNote = useCallback(async (parentNoteId?: string): Promise<void> => {
    const created = await notes.handleCreateNote(parentNoteId)
    if (created) {
      setSectionNoteOpen(true)
      openWorkspaceNote(created.id)
      auth.setStatusMessage('Note created.')
    } else {
      auth.setErrorMessage('Cannot create note')
    }
  }, [notes, openWorkspaceNote, auth, setSectionNoteOpen])

  const handleDeleteNote = useCallback(async (noteId: string): Promise<void> => {
    const removedIds = await notes.handleDeleteNote(noteId)
    if (removedIds.length > 0) {
      if (routeWorkspaceState.noteId && new Set(removedIds).has(routeWorkspaceState.noteId)) {
        const remaining = notes.recentNotes.filter((n) => !removedIds.includes(n.id))
        const nextId = remaining[0]?.id ?? null
        const workspaceId = workspaces.currentWorkspace?.id
        if (activeWorkspaceView === 'note' && workspaceId) {
          navigate(nextId ? noteRoute(workspaceId, nextId) : workspaceRoute(workspaceId))
        }
      }
      auth.setStatusMessage('Note deleted.')
    } else {
      auth.setErrorMessage('Cannot delete note')
    }
  }, [notes, activeWorkspaceView, navigate, workspaces.currentWorkspace, auth, routeWorkspaceState.noteId, noteRoute])

  const handleWorkspaceSidebarDrop = useCallback(async (targetParentId: string | null): Promise<void> => {
    await notes.handleWorkspaceSidebarDrop(targetParentId)
  }, [notes])

const renderWorkspaceSidebarNoteTree = useCallback((parentId: string | null, depth: number): React.ReactNode => {
     const childNotes = notes.workspaceNotesByParent.get(parentId) ?? []
     if (!childNotes.length) return null

     return childNotes.map((note) => (
       <div key={note.id}>
         <button
           type="button"
        className={[
              'app-sidebar-sub-item',
               activeWorkspaceView === 'note' && routeWorkspaceState.noteId === note.id ? 'active' : '',
               notes.workspaceDropTargetParentId === note.id ? 'workspace-nav-item--drop-target' : '',
            ].filter(Boolean).join(' ')}
           style={{ paddingLeft: `${10 + (depth * 14)}px` }}
           onClick={() => openWorkspaceNote(note.id)}
           title={note.title}
           draggable
           onDragStart={(e) => {
             e.dataTransfer.effectAllowed = 'move'
             e.dataTransfer.setData('text/plain', note.id)
             notes.setWorkspaceDraggingNoteId(note.id)
             notes.setWorkspaceDropTargetParentId(null)
           }}
           onDragEnd={() => {
             notes.setWorkspaceDraggingNoteId(null)
             notes.setWorkspaceDropTargetParentId(null)
           }}
           onDragOver={(e) => {
             if (!notes.workspaceDraggingNoteId || !notes.canMoveWorkspaceNote(notes.workspaceDraggingNoteId, note.id)) return
             e.preventDefault()
             e.stopPropagation()
             e.dataTransfer.dropEffect = 'move'
             notes.setWorkspaceDropTargetParentId(note.id)
           }}
           onDrop={(e) => {
             e.preventDefault()
             e.stopPropagation()
             void handleWorkspaceSidebarDrop(note.id)
             notes.setWorkspaceDraggingNoteId(null)
             notes.setWorkspaceDropTargetParentId(null)
           }}
         >
           <StickyNote size={13} />
           <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{note.title}</span>
            <div className="workspace-nav-item-actions">
              <button
                type="button"
                className="app-sidebar-sub-action-btn danger"
               title="Delete"
               onClick={(e) => {
                 e.stopPropagation()
                 if (window.confirm('Are you sure you want to delete this note?')) {
                   void handleDeleteNote(note.id)
                 }
               }}
             >
               <Trash2 size={12} />
             </button>
           </div>
         </button>
         {/* eslint-disable-next-line react-hooks/immutability */}
         {renderWorkspaceSidebarNoteTree(note.id, depth + 1)}
       </div>
     ))
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [notes.workspaceNotesByParent, activeWorkspaceView, routeWorkspaceState.noteId, notes.workspaceDropTargetParentId,
        notes.workspaceDraggingNoteId, notes.canMoveWorkspaceNote])

  const handleNoteChange = useCallback((id: string, contentMd: string) => {
    notes.handleNoteChange(id, contentMd)
  }, [notes])

  const handleNoteTitleChange = useCallback((id: string, title: string) => {
    notes.handleTitleChange(id, title)
  }, [notes])

  const handleCalendarSlotSelect = useCallback((slotStart: Date, slotEnd: Date) => {
    const toLocalInputDateTime = (value: Date): string => {
      const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
      return local.toISOString().slice(0, 16)
    }
    setCreateEventInitialTimes({
      startDate: toLocalInputDateTime(slotStart),
      endDate: toLocalInputDateTime(slotEnd),
    })
    setIsCreateEventOpen(true)
  }, [])

  const handleOpenCreateEvent = useCallback(() => {
    setCreateEventInitialTimes(null)
    setIsCreateEventOpen(true)
  }, [])

  const handleCloseCreateEvent = useCallback(() => {
    setIsCreateEventOpen(false)
    setCreateEventInitialTimes(null)
  }, [])

// SSE for calendar sync
   useEffect(() => {
     if (!auth.tokens?.accessToken) return

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
         void schedules.fetchSchedules()
         void schedules.fetchGoogleCalendarStatus()
       } catch {
         // Ignore malformed SSE payloads
       }
     }

    const connect = async () => {
      const tabAppId = getOrCreateSseTabAppId()
      const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
      const sseUrl = `${API_BASE_URL}/sse/sync/events?appid=${encodeURIComponent(tabAppId)}`
      let retryDelayMs = 3000
      const maxRetryDelayMs = 30000

      while (!isStopped) {
        try {
          // Always get fresh token from store, not from state closure
          const tokens = getCurrentTokens()
          if (!tokens?.accessToken) {
            throw new Error('No valid tokens available')
          }

          const response = await fetch(sseUrl, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: 'text/event-stream',
            },
            signal: abortController.signal,
          })

          // Handle 401 - token expired
          if (response.status === 401) {
            if (tokens.refreshToken) {
              try {
                // Attempt to refresh token
                const refreshResponse = await fetch(`${API_BASE_URL}/auth/refresh`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ refresh_token: tokens.refreshToken }),
                })
                const refreshData = await refreshResponse.json()
                if (refreshData.access_token && refreshData.refresh_token) {
                  const newTokens = { accessToken: refreshData.access_token, refreshToken: refreshData.refresh_token }
                  setCurrentTokens(newTokens)
                  // Retry SSE connection with new token
                  await sleep(1000)
                  continue
                }
              } catch {
                // Refresh failed, disconnect SSE
                break
              }
            } else {
              break
            }
          }

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
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens?.accessToken])

// SSE for real-time notifications
   useEffect(() => {
    if (!auth.tokens?.accessToken) return

    const abortController = new AbortController()
    let isStopped = false

    const sleep = (ms: number) => new Promise((resolve) => {
      window.setTimeout(resolve, ms)
    })

const processNotificationChunk = (chunk: string): void => {
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
          const payload = JSON.parse(rawData) as {
            event: string
            notification_id: string
            title: string
            body: string
            content?: { type: string; text?: string; url?: string; html?: string; language?: string; content?: string }[]
            actions?: { label: string; action: string; url?: string; payload?: Record<string, unknown> }[]
            type: string
            payload: Record<string, unknown>
            occurred_at: string
          }
          if (payload.event !== 'notification.created') return

          const newNotif: AppNotification = {
            id: payload.notification_id,
            kind: (payload.type as NotificationKind) || 'system',
            title: payload.title,
            body: payload.body,
            timestamp: new Date(payload.occurred_at),
            read: false,
            payload: payload.payload || {},
            content: payload.content as AppNotification['content'],
            actions: payload.actions as AppNotification['actions'],
          }
          notif.addNotification(newNotif)

         // Browser notification
         if ('Notification' in window && Notification.permission === 'granted') {
           const notification = new Notification(payload.title, {
             body: payload.body,
             icon: '/favicon.ico',
             tag: payload.notification_id,
           })
           notification.onclick = () => {
             if (payload.payload?.navigate_to) {
               navigate(String(payload.payload.navigate_to))
             }
             window.focus()
             notification.close()
           }
         }
       } catch {
         // Ignore malformed SSE payloads
       }
     }

    const connect = async () => {
      const tabAppId = getOrCreateSseTabAppId()
      const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000/api'
      const sseUrl = `${API_BASE_URL}/sse/notifications/events?appid=${encodeURIComponent(tabAppId)}`
      let retryDelayMs = 3000
      const maxRetryDelayMs = 30000

      while (!isStopped) {
        try {
          const tokens = getCurrentTokens()
          if (!tokens?.accessToken) {
            throw new Error('No valid tokens available')
          }

          const response = await fetch(sseUrl, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${tokens.accessToken}`,
              Accept: 'text/event-stream',
            },
            signal: abortController.signal,
          })

          if (response.status === 401) {
            if (tokens.refreshToken) {
              try {
                const refreshResponse = await fetch(`${API_BASE_URL}/auth/refresh`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ refresh_token: tokens.refreshToken }),
                })
                const refreshData = await refreshResponse.json()
                if (refreshData.access_token && refreshData.refresh_token) {
                  const newTokens = { accessToken: refreshData.access_token, refreshToken: refreshData.refresh_token }
                  setCurrentTokens(newTokens)
                  await sleep(1000)
                  continue
                }
              } catch {
                break
              }
            } else {
              break
            }
          }

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
              processNotificationChunk(chunk)
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
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens?.accessToken])

  const userInitial = auth.user?.full_name?.[0]?.toUpperCase() ?? auth.user?.email?.[0]?.toUpperCase() ?? '?'

  return (
    <div className="app-shell">
      {/* TOP BAR */}
      <header className="topbar">
        <div className="topbar-left">
          <div className="brand-logo">
            <div className="brand-icon">C</div>
            <span className="brand-name">Cortex</span>
          </div>
          {auth.tokens && (
            <div className="topbar-search">
              <Search size={16} className="topbar-search-icon" />
              <input
                className="topbar-search-input"
                type="text"
                placeholder="Search workflows, nodes, history..."
                onClick={() => setIsSearchOpen(true)}
                readOnly
              />
              <div className="topbar-search-hint">
                <kbd>⌘</kbd>
                <kbd>K</kbd>
              </div>
            </div>
          )}
        </div>

        <div className="topbar-right">
          {auth.tokens && (
            <>
              <button
                type="button"
                className="topbar-btn-ask-ai"
                onClick={() => setIsAskAIOpen(prev => !prev)}
                title="Ask AI"
              >
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 3l1.5 3.5L17 8l-3.5 1.5L12 13l-1.5-3.5L7 8l3.5-1.5L12 3z" />
                  <path d="M18 13l1 2.5L21 17l-2.5 1L18 21l-1-2.5L14 17l2.5-1L18 13z" />
                  <path d="M6 13l1 2.5L9 17l-2.5 1L6 21l-1-2.5L2 17l2.5-1L6 13z" />
                </svg>
                Ask AI
              </button>
              <NotificationBell
                notifications={notif.notifications}
                onMarkRead={notif.handleMarkRead}
                onMarkAllRead={notif.handleMarkAllRead}
                onDismiss={notif.handleDismiss}
                onNavigate={navigate}
              />
              <button type="button" className="topbar-icon-btn" title="Help">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </button>
              <div className="user-avatar" title={auth.user?.email}>{userInitial}</div>
            </>
          )}
        </div>
      </header>

      {/* STATUS BAR */}
      {auth.statusMessage && !auth.errorMessage && (
        <div className="status-bar ok">
          <CheckCircle2 size={14} />
          <span>{auth.statusMessage}</span>
        </div>
      )}
      {auth.errorMessage && (
        <div className="status-bar error">
          <AlertCircle size={14} />
          <span>{auth.errorMessage}</span>
        </div>
      )}

      {/* MAIN CONTENT */}
      {!auth.tokens ? (
        <div className="main-layout">
          <AuthPanel onLogin={auth.handleLogin} onRegister={auth.handleRegister} isBusy={auth.isBusy} />
        </div>
      ) : (
        <div className="main-layout">
          <aside className="app-sidebar">
            <div className="app-sidebar-profile">
              {workspaces.currentWorkspace && (
                <WorkspaceSwitcher
                  workspaces={workspaces.workspaces}
                  currentWorkspace={workspaces.currentWorkspace}
                  onSwitch={handleWorkspaceSwitch}
                  onCreateWorkspace={() => setIsCreateWorkspaceOpen(true)}
                  onRenameWorkspace={workspaces.renameWorkspace}
                  onDeleteWorkspace={workspaces.deleteWorkspace}
                  onManageMembers={(workspace) => {
                    setManagingMembersWorkspace({
                      id: workspace.id,
                      name: workspace.name,
                      is_personal: workspace.is_personal,
                    })
                  }}
                  onOpenSettings={(workspace) => {
                    setSettingsWorkspace(workspace)
                  }}
                  isCollapsed={isWorkspaceSidebarCollapsed}
                  user={auth.user}
                />
              )}
            </div>

            <div className="app-sidebar-nav">
                <button
                  type="button"
                  className={`app-sidebar-nav-item ${location.pathname === '/' ? 'active' : ''}`}
                  onClick={() => navigate('/')}
                >
                  <Home size={16} />
                  <span className="app-sidebar-nav-label">HOME</span>
                </button>

                <button
                  type="button"
                  className="app-sidebar-nav-item"
                  onClick={() => {/* TODO: Navigate to notifications */ }}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                  <span className="app-sidebar-nav-label">NOTIFICATIONS</span>
                </button>

                <button
                  type="button"
                  className={`app-sidebar-nav-item ${location.pathname === '/schedule' ? 'active' : ''}`}
                  onClick={() => navigate(scheduleRoute())}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                    <line x1="16" y1="2" x2="16" y2="6" />
                    <line x1="8" y1="2" x2="8" y2="6" />
                    <line x1="3" y1="10" x2="21" y2="10" />
                  </svg>
                  <span className="app-sidebar-nav-label">SCHEDULE</span>
                </button>
              </div>

            {workspaces.currentWorkspace && (
              <>
                <div className="app-sidebar-sections">

                  <SidebarSection
                    icon={<StickyNote size={15} />}
                    label="Notes"
                    isOpen={sectionNoteOpen}
                    onToggle={() => setSectionNoteOpen(v => !v)}
                    isCollapsed={isWorkspaceSidebarCollapsed}
                    sectionBodyProps={{
                      className: notes.workspaceDropTargetParentId === null ? 'sidebar-section-body--drop-target' : '',
                      onDragOver: (e) => {
                        if (!notes.workspaceDraggingNoteId || !notes.canMoveWorkspaceNote(notes.workspaceDraggingNoteId, null)) return
                        e.preventDefault()
                        e.dataTransfer.dropEffect = 'move'
                        notes.setWorkspaceDropTargetParentId(null)
                      },
                      onDrop: (e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        void handleWorkspaceSidebarDrop(null)
                        notes.setWorkspaceDraggingNoteId(null)
                        notes.setWorkspaceDropTargetParentId(null)
                      },
                      onDragLeave: (e) => {
                        if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
                          notes.setWorkspaceDropTargetParentId(null)
                        }
                      },
                    }}
                  >
                    <div className="workspace-note-links">
                      {notes.workspaceRootNotes.length === 0 ? (
                        <div className="app-sidebar-sub-item" style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          <span>No notes yet</span>
                        </div>
                      ) : (
                        <>
                          {notes.workspaceRootNotes.map((note) => (
                            <div key={note.id}>
                              <button
                                type="button"
                                className={[
                                  'app-sidebar-sub-item',
                                  activeWorkspaceView === 'note' && routeWorkspaceState.noteId === note.id ? 'active' : '',
                                  notes.workspaceDropTargetParentId === note.id ? 'workspace-nav-item--drop-target' : '',
                                ].filter(Boolean).join(' ')}
                                onClick={() => openWorkspaceNote(note.id)}
                                title={note.title}
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.effectAllowed = 'move'
                                  e.dataTransfer.setData('text/plain', note.id)
                                  notes.setWorkspaceDraggingNoteId(note.id)
                                  notes.setWorkspaceDropTargetParentId(null)
                                }}
                                onDragEnd={() => {
                                  notes.setWorkspaceDraggingNoteId(null)
                                  notes.setWorkspaceDropTargetParentId(null)
                                }}
                                onDragOver={(e) => {
                                  if (!notes.workspaceDraggingNoteId || !notes.canMoveWorkspaceNote(notes.workspaceDraggingNoteId, note.id)) return
                                  e.preventDefault()
                                  e.stopPropagation()
                                  e.dataTransfer.dropEffect = 'move'
                                  notes.setWorkspaceDropTargetParentId(note.id)
                                }}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  void handleWorkspaceSidebarDrop(note.id)
                                  notes.setWorkspaceDraggingNoteId(null)
                                  notes.setWorkspaceDropTargetParentId(null)
                                }}
                              >
                                <StickyNote size={13} />
                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{note.title}</span>
                                <div className="workspace-nav-item-actions">
                                  <button
                                    type="button"
                                    className="app-sidebar-sub-action-btn danger"
                                    title="Delete"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      if (window.confirm('Are you sure you want to delete this note?')) {
                                        void handleDeleteNote(note.id)
                                      }
                                    }}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </button>
                              {renderWorkspaceSidebarNoteTree(note.id, 1)}
                            </div>
                          ))}
                        </>
                      )}
                      <button
                        type="button"
                        className="app-sidebar-sub-item app-sidebar-sub-item--add"
                        onClick={() => handleCreateNote(routeWorkspaceState.noteId ?? undefined)}
                        title={routeWorkspaceState.noteId ? 'Add sub-note' : 'New note'}
                      >
                        <Plus size={13} />
                        <span>{routeWorkspaceState.noteId ? 'Add sub-note' : 'New note'}</span>
                      </button>
                    </div>
                  </SidebarSection>

                  <SidebarSection
                    icon={<Video size={15} />}
                    label="Records"
                    isOpen={sectionRecordOpen}
                    onToggle={() => {
                      setSectionRecordOpen(v => !v)
                    }}
                    isCollapsed={isWorkspaceSidebarCollapsed}
                    onLabelClick={() => {
                      const workspaceId = workspaces.currentWorkspace?.id
                      if (workspaceId) navigate(workspaceRoute(workspaceId, '/records'))
                    }}
                  >
                    <div className="workspace-note-links">
                      {assets.sidebarAssetsLoading ? (
                        <div className="app-sidebar-sub-item" >
                          <Video size={13} />
                          <span>Loading...</span>
                        </div>
                      ) : assets.sidebarAssets.length === 0 ? (
                        <div className="app-sidebar-sub-item" >
                          <Video size={13} />
                          <span>No recordings yet</span>
                        </div>
                      ) : (
                        <>
                          {assets.sidebarAssets.map(asset => {
                            const displayName = asset.title || asset.id.slice(0, 8)
                            return (
                              <button
                                key={asset.id}
                                type="button"
                                className={`app-sidebar-sub-item ${activeWorkspaceView === 'records' && activeWorkspaceAssetId === asset.id ? 'active' : ''}`}
                                onClick={() => {
                                  const workspaceId = workspaces.currentWorkspace?.id
                                  if (workspaceId) navigate(knowledgeRoute(workspaceId, asset.id))
                                }}
                                title={displayName}
                              >
                                <Video size={13} />
                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{displayName}</span>
                                <div className="workspace-nav-item-actions">
                                  <button
                                    type="button"
                                    className="app-sidebar-sub-action-btn danger"
                                    title="Delete"
                                    onClick={async (e) => {
                                      e.stopPropagation()
                                      if (window.confirm('Are you sure you want to delete this recording?')) {
                                        const deleted = await assets.deleteAsset(asset.id)
                                        if (deleted) {
                                          void assets.loadSidebarAssets()
                                        }
                                      }
                                    }}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </button>
                            )
                          })}
                        </>
                      )}
                    </div>
                  </SidebarSection>

                  <SidebarSection
                    icon={<GitBranch size={15} />}
                    label="Workflows"
                    isOpen={true}
                    onToggle={() => {}}
                    isCollapsed={isWorkspaceSidebarCollapsed}
                    onLabelClick={() => {
                      const workspaceId = workspaces.currentWorkspace?.id
                      if (workspaceId) navigate(workflowRoute(workspaceId))
                    }}
                  >
                    <div className="workspace-note-links">
                      <button
                        type="button"
                        className="app-sidebar-sub-item"
                        onClick={() => {
                          const workspaceId = workspaces.currentWorkspace?.id
                          if (workspaceId) navigate(workflowRoute(workspaceId))
                        }}
                      >
                        <Plus size={13} />
                        <span>New Workflow</span>
                      </button>
                    </div>
                  </SidebarSection>
                </div>
              </>
            )}

            <div className="app-sidebar-footer">
              <button
                type="button"
                className={`app-sidebar-nav-item ${activeWorkspaceView === 'settings' ? 'active' : ''}`}
                onClick={() => navigate('/settings')}
              >
                <Settings size={16} />
                <span className="app-sidebar-nav-label">SETTINGS</span>
              </button>
            </div>
          </aside>

          <div className="workspace-area" style={{ maxWidth: '100%' }}>
            {activeWorkspaceView === 'settings' ? (
              <SettingsPanel
                googleCalendarStatus={schedules.googleCalendarStatus}
                onConnectGoogleCalendar={schedules.handleConnectGoogleCalendar}
                onSyncGoogleCalendarNow={schedules.handleSyncGoogleCalendarNow}
                onStartGoogleCalendarWatch={schedules.handleStartGoogleCalendarWatch}
                onRenewGoogleCalendarWatch={schedules.handleRenewGoogleCalendarWatch}
                onDisconnectGoogleCalendar={schedules.handleDisconnectGoogleCalendar}
                theme={theme}
                onThemeChange={_setTheme}
                formatDateTimeVi={(isoDateTime: string | null) => {
                  if (!isoDateTime) return ''
                  const date = new Date(isoDateTime)
                  return date.toLocaleString('vi-VN', { dateStyle: 'short', timeStyle: 'short' })
                }}
                blockEditingEnabled={blockEditingEnabled}
                onBlockEditingChange={(enabled) => {
                  _setBlockEditingEnabled(enabled)
                  setBlockEditingEnabled(enabled)
                }}
              />
            ) : activeWorkspaceView === 'schedule' ? (
              <section className="home-workspace">
                <div className="home-schedule-area">
                  <CalendarView
                    schedules={schedules.schedules}
                    isGoogleCalendarConnected={Boolean(schedules.googleCalendarStatus?.connected)}
                    startDate={schedules.startDate}
                    endDate={schedules.endDate}
                    onStartDateChange={schedules.setStartDate}
                    onEndDateChange={schedules.setEndDate}
                    onFetch={() => void schedules.fetchSchedules()}
                    onOpenCreateEvent={handleOpenCreateEvent}
                    onSlotSelect={handleCalendarSlotSelect}
                    onToggleComplete={schedules.handleToggleComplete}
                    onRemove={schedules.handleRemoveSchedule}
                  />
                </div>
              </section>
            ) : activeWorkspaceView === 'workflow' ? (
              <WorkflowBuilder
                workspaceId={workspaces.currentWorkspace?.id ?? null}
                workflowId={activeWorkspaceWorkflowId}
                onBack={() => {
                  const workspaceId = workspaces.currentWorkspace?.id
                  if (workspaceId) navigate(workflowRoute(workspaceId))
                }}
                onNavigate={(wfId) => {
                  const workspaceId = workspaces.currentWorkspace?.id
                  if (workspaceId) navigate(workflowRoute(workspaceId, wfId))
                }}
              />
            ) : !routeWorkspaceState.workspaceId ? (
              <GlobalHome
                user={auth.user}
                workspaces={workspaces.workspaces}
                recentNotes={notes.recentNotes}
                upcomingSchedules={schedules.schedules}
                onCreateNote={() => {
                  if (workspaces.currentWorkspace) {
                    handleCreateNote()
                  } else if (workspaces.workspaces.length > 0) {
                    handleWorkspaceSwitch(workspaces.workspaces[0])
                  }
                }}
                onCreateEvent={() => setIsCreateEventOpen(true)}
                onCreateWorkspace={() => setIsCreateWorkspaceOpen(true)}
                onOpenWorkspace={(workspaceId) => {
                  const workspace = workspaces.workspaces.find(ws => ws.id === workspaceId)
                  if (workspace) handleWorkspaceSwitch(workspace)
                }}
                onOpenNote={(noteId) => openWorkspaceNote(noteId)}
              />
            ) : activeWorkspaceView === 'records' ? (
              <RecordPanel
                requestWithAuth={requestWithAuth}
                isVisible
                initialAssetId={activeWorkspaceAssetId}
                onAssetViewed={() => {
                  const workspaceId = workspaces.currentWorkspace?.id
                  if (workspaceId) {
                    navigate(workspaceRoute(workspaceId, '/records'))
                  }
                }}
                workspaceId={workspaces.currentWorkspace?.id}
                onAssetChange={() => {
                  void assets.loadSidebarAssets()
                }}
              />
            ) : activeWorkspaceView === 'knowledge' && activeWorkspaceKnowledgeAssetId ? (
              <AssetKnowledgeView
                assetId={activeWorkspaceKnowledgeAssetId}
                requestWithAuth={requestWithAuth}
                onClose={() => {
                  const workspaceId = workspaces.currentWorkspace?.id
                  if (workspaceId) navigate(workspaceRoute(workspaceId, '/records'))
                }}
              />
            ) : notes.activeWorkspaceNote ? (
              <div className="workspace-note-page">
                <WorkspaceNoteEditor
                  note={notes.activeWorkspaceNote}
                  onChange={handleNoteChange}
                  onTitleChange={handleNoteTitleChange}
                  onAskAI={() => setIsAskAIOpen(true)}
                  onSelectionChange={(text) => setPendingSelection(text)}
                  blockEditingEnabled={blockEditingEnabled}
                />
              </div>
            ) : (
              <section className="workspace-empty-note">
                <p>Chọn một note từ sidebar để mở trong workspace.</p>
              </section>
            )}
          </div>

          {/* AskAI Side Panel */}
          {auth.tokens && isAskAIOpen && (
            <div className="ask-ai-sidebar">
              <AskAI
                noteContent={notes.activeWorkspaceNote?.contentMd}
                noteTitle={notes.activeWorkspaceNote ? noteTitleFromMd(notes.activeWorkspaceNote.contentMd) : undefined}
                pendingSelection={pendingSelection}
                workspaceId={workspaces.currentWorkspace?.id}
                onClose={() => setIsAskAIOpen(false)}
                onInsert={(text) => {
                  if (!notes.activeWorkspaceNote) return
                  const newContent = notes.activeWorkspaceNote.contentMd + '\n\n' + text
                  handleNoteChange(notes.activeWorkspaceNote.id, newContent)
                }}
                onToolNavigate={async (toolName: string) => {
                  if (toolName === 'create_note') {
                    await notes.fetchNotes()
                  } else if (toolName === 'schedule') {
                    await schedules.fetchSchedules()
                  } else if (toolName === 'knowledge') {
                    await assets.loadSidebarAssets()
                  }
                }}
              />
            </div>
          )}
        </div >
      )
      }

      {/* CREATE EVENT MODAL */}
      {
        auth.tokens && isCreateEventOpen && (
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
                  onCreate={schedules.handleCreateSchedule}
                  initialTimes={createEventInitialTimes}
                  onClose={handleCloseCreateEvent}
                />
              </div>
            </div>
          </div>
        )
      }

      {
        auth.tokens && isSearchOpen && (
          <WorkspaceSearch
            notes={notes.recentNotes}
            onOpenNote={(noteId) => {
              openWorkspaceNote(noteId)
            }}
            onClose={() => setIsSearchOpen(false)}
          />
        )
      }

      {/* Create Workspace Modal */}
      {
        auth.tokens && isCreateWorkspaceOpen && (
          <WorkspaceCreateModal
            onClose={() => setIsCreateWorkspaceOpen(false)}
            onCreated={(workspaceId) => {
              setIsCreateWorkspaceOpen(false)
              const workspace = workspaces.workspaces.find(ws => ws.id === workspaceId)
              if (workspace) {
                handleWorkspaceSwitch(workspace)
              }
            }}
            onCreateWorkspace={workspaces.createWorkspace}
          />
        )
      }

      {/* Manage Members Modal */}
      {
        auth.tokens && managingMembersWorkspace && (
          <WorkspaceMembersModal
            workspace={managingMembersWorkspace}
            members={[]}
            onClose={() => setManagingMembersWorkspace(null)}
            onAddMember={async (email, role) => {
              const success = await workspaces.addMember(managingMembersWorkspace.id, email, role)
              if (success) {
                // TODO: Refresh members list
              }
              return success
            }}
            onRemoveMember={async (userId) => {
              const success = await workspaces.removeMember(managingMembersWorkspace.id, userId)
              if (success) {
                // TODO: Refresh members list
              }
              return success
            }}
            onChangeRole={async (userId, role) => {
              const success = await workspaces.changeMemberRole(managingMembersWorkspace.id, userId, role)
              if (success) {
                // TODO: Refresh members list
              }
              return success
            }}
          />
        )
      }

      {/* Workspace Settings Modal */}
      {
        auth.tokens && settingsWorkspace && (
          <WorkspaceSettingsModal
            workspace={settingsWorkspace}
            onClose={() => setSettingsWorkspace(null)}
            onRenameWorkspace={async (id, name) => {
              const ok = await workspaces.renameWorkspace(id, name)
              if (ok) {
                // Update local settingsWorkspace to reflect new name
                setSettingsWorkspace(prev => prev ? { ...prev, name } : null)
              }
              return ok
            }}
            onDeleteWorkspace={async (id) => {
              const ok = await workspaces.deleteWorkspace(id)
              if (ok) setSettingsWorkspace(null)
              return ok
            }}
            onAddMember={async (email, role) => {
              return workspaces.addMember(settingsWorkspace.id, email, role)
            }}
            onRemoveMember={async (userId) => {
              return workspaces.removeMember(settingsWorkspace.id, userId)
            }}
            onChangeRole={async (userId, role) => {
              return workspaces.changeMemberRole(settingsWorkspace.id, userId, role)
            }}
            members={[]}
            currentUserId={auth.user?.id}
          />
        )
      }
    </div >
  )
}

export default App