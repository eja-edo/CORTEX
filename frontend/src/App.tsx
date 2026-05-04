import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronRight, Home, LogOut, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, StickyNote, Video, X, Trash2 } from 'lucide-react'
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
import type { SyncUpdateEvent } from './types'
import { NotificationBell, type AppNotification } from './components/NotificationBell'
import { WorkspaceNoteEditor } from './components/WorkspaceNoteEditor'
import { WorkspaceSearch } from './components/WorkspaceSearch'
import { WorkspaceSwitcher } from './components/WorkspaceSwitcher'
import { WorkspaceCreateModal } from './components/WorkspaceCreateModal'
import { WorkspaceMembersModal } from './components/WorkspaceMembersModal'
import { WorkspaceSettingsModal } from './components/WorkspaceSettingsModal'
import { GlobalHome } from './components/GlobalHome'
import { AskAI } from './components/AskAI'
import { getStoredTheme, applyThemeToDocument } from './utils/theme'
import type { AppTheme } from './utils/theme'
import { useAuth } from './hooks/useAuth'
import { useWorkspaces } from './hooks/useWorkspaces'
import { useNotes, noteTitleFromMd } from './hooks/useNotes'
import { useSchedules } from './hooks/useSchedules'
import { useAssets } from './hooks/useAssets'
import { requestWithAuth } from './services/api'
import { extractWorkspaceId, isWorkspaceRoute, noteRoute, knowledgeRoute, workspaceRoute } from './services/routes'
import type { Workspace } from './types'

const SSE_TAB_APPID_KEY = 'cortex_sse_appid'

type WorkspaceView = 'dashboard' | 'note' | 'records' | 'knowledge' | 'schedule'

function getRouteWorkspaceState(pathname: string): {
  view: WorkspaceView
  workspaceId: string | null
  noteId: string | null
  assetId: string | null
} {
  const workspaceId = extractWorkspaceId(pathname)

  if (workspaceId) {
    const knowledgeMatch = matchPath('/w/:workspaceId/records/:assetId/knowledge', pathname)
    if (knowledgeMatch?.params.assetId) {
      return {
        view: 'knowledge',
        workspaceId,
        noteId: null,
        assetId: knowledgeMatch.params.assetId
      }
    }

    const noteMatch = matchPath('/w/:workspaceId/notes/:noteId', pathname)
    if (noteMatch?.params.noteId) {
      return {
        view: 'note',
        workspaceId,
        noteId: noteMatch.params.noteId,
        assetId: null
      }
    }

    if (matchPath('/w/:workspaceId/records', pathname)) {
      return { view: 'records', workspaceId, noteId: null, assetId: null }
    }

    if (matchPath('/w/:workspaceId/schedule', pathname)) {
      return { view: 'schedule', workspaceId, noteId: null, assetId: null }
    }

    if (matchPath('/w/:workspaceId', pathname) || matchPath('/w/:workspaceId/notes', pathname)) {
      return { view: 'dashboard', workspaceId, noteId: null, assetId: null }
    }
  }

  return { view: 'dashboard', workspaceId: null, noteId: null, assetId: null }
}

function isKnownRoute(pathname: string): boolean {
  return pathname === '/'
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
        className="workspace-sidebar-section-title sidebar-section-toggle"
        onClick={onToggle}
        aria-expanded={isOpen}
        title={label}
      >
        <span className="sidebar-section-toggle-icon">{icon}</span>
        {!isCollapsed && (
          <>
            <span
              className="sidebar-section-toggle-label"
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
            <span className="sidebar-section-toggle-chevron">
              {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            </span>
          </>
        )}
      </button>
      {isOpen && !isCollapsed && (
        <div
          className={[
            'sidebar-section-body',
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
  const [isAskAIOpen, setIsAskAIOpen] = useState(false)
  const [pendingSelection, setPendingSelection] = useState<string>('')
  const [isCreateWorkspaceOpen, setIsCreateWorkspaceOpen] = useState(false)
  const [managingMembersWorkspace, setManagingMembersWorkspace] = useState<{ id: string; name: string; is_personal: boolean } | null>(null)
  const [settingsWorkspace, setSettingsWorkspace] = useState<Workspace | null>(null)
  const [createEventInitialTimes, setCreateEventInitialTimes] = useState<{ startDate: string; endDate: string } | null>(null)
  const [isWorkspaceSidebarCollapsed, setIsWorkspaceSidebarCollapsed] = useState<boolean>(false)
  const [theme, _setTheme] = useState<AppTheme>(getStoredTheme)
  const [sectionNoteOpen, setSectionNoteOpen] = useState(true)
  const [sectionRecordOpen, setSectionRecordOpen] = useState(true)
  const [notifications, setNotifications] = useState<AppNotification[]>([])
  const syncToastTimerRef = useRef<number | null>(null)

  const activeWorkspaceView = routeWorkspaceState.view
  const [activeWorkspaceNoteId, setActiveWorkspaceNoteId] = useState<string | null>(routeWorkspaceState.noteId)
  const [activeWorkspaceAssetId, setActiveWorkspaceAssetId] = useState<string | null>(routeWorkspaceState.assetId)
  const [activeWorkspaceKnowledgeAssetId, setActiveWorkspaceKnowledgeAssetId] = useState<string | null>(routeWorkspaceState.assetId)

  useEffect(() => {
    setActiveWorkspaceNoteId(routeWorkspaceState.noteId)
    setActiveWorkspaceAssetId(routeWorkspaceState.assetId)
    if (routeWorkspaceState.view === 'knowledge') {
      setActiveWorkspaceKnowledgeAssetId(routeWorkspaceState.assetId)
    }
  }, [routeWorkspaceState.noteId, routeWorkspaceState.assetId, routeWorkspaceState.view])

  useEffect(() => {
    applyThemeToDocument(theme)
    window.localStorage.setItem('cortex_theme', theme)
  }, [theme])

  useEffect(() => {
    if (isKnownRoute(location.pathname)) return
    navigate('/', { replace: true })
  }, [location.pathname, navigate])

  useEffect(() => {
    if (!sectionRecordOpen || !auth.tokens || !workspaces.currentWorkspace) return
    void assets.loadSidebarAssets()
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
  }, [auth.tokens])

  useEffect(() => {
    if (!routeWorkspaceState.workspaceId || workspaces.workspaces.length === 0) return

    const targetWorkspace = workspaces.workspaces.find(ws => ws.id === routeWorkspaceState.workspaceId)
    if (targetWorkspace && targetWorkspace.id !== workspaces.currentWorkspace?.id) {
      workspaces.setCurrentWorkspace(targetWorkspace)
    }
  }, [routeWorkspaceState.workspaceId, workspaces.workspaces])

  useEffect(() => {
    if (!auth.tokens) return
    void notes.fetchNotes()
  }, [auth.tokens, workspaces.currentWorkspace])

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
  }, [])

  function showSyncToast(message: string): void {
    auth.setStatusMessage(message)
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
      auth.setStatusMessage('')
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

  const handleWorkspaceSwitch = useCallback((workspace: typeof workspaces.currentWorkspace): void => {
    if (!workspace || workspace.id === workspaces.currentWorkspace?.id) return

    notes.clearNotes()
    workspaces.switchWorkspace(workspace)
    setActiveWorkspaceNoteId(null)
    navigate(workspaceRoute(workspace.id), { replace: true })
  }, [navigate, notes, workspaces])

  const openWorkspaceNote = useCallback((noteId: string) => {
    setActiveWorkspaceNoteId(noteId)
    const workspaceId = workspaces.currentWorkspace?.id
    if (workspaceId) {
      navigate(noteRoute(workspaceId, noteId))
    }
  }, [navigate, workspaces.currentWorkspace])

  const handleCreateNote = useCallback(async (parentNoteId?: string): Promise<void> => {
    const created = await notes.handleCreateNote(parentNoteId)
    if (created) {
      openWorkspaceNote(created.id)
      auth.setStatusMessage('Note created.')
    } else {
      auth.setErrorMessage('Cannot create note')
    }
  }, [notes, openWorkspaceNote, auth])

  const handleDeleteNote = useCallback(async (noteId: string): Promise<void> => {
    const removedIds = await notes.handleDeleteNote(noteId)
    if (removedIds.length > 0) {
      if (activeWorkspaceNoteId && new Set(removedIds).has(activeWorkspaceNoteId)) {
        const remaining = notes.recentNotes.filter((n) => !removedIds.includes(n.id))
        setActiveWorkspaceNoteId(remaining[0]?.id ?? null)
        const workspaceId = workspaces.currentWorkspace?.id
        if (activeWorkspaceView === 'note' && workspaceId) {
          navigate(workspaceRoute(workspaceId))
        }
      }
      auth.setStatusMessage('Note deleted.')
    } else {
      auth.setErrorMessage('Cannot delete note')
    }
  }, [notes, activeWorkspaceNoteId, activeWorkspaceView, navigate, workspaces.currentWorkspace, auth])

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
            'workspace-nav-item',
            'workspace-nav-item--sub',
            activeWorkspaceView === 'note' && activeWorkspaceNoteId === note.id ? 'active' : '',
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
              className="workspace-nav-action-btn danger"
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
        {renderWorkspaceSidebarNoteTree(note.id, depth + 1)}
      </div>
    ))
  }, [
    notes.workspaceNotesByParent,
    activeWorkspaceView,
    activeWorkspaceNoteId,
    notes.workspaceDropTargetParentId,
    openWorkspaceNote,
    notes.workspaceDraggingNoteId,
    notes.canMoveWorkspaceNote,
    handleWorkspaceSidebarDrop,
    notes.setWorkspaceDraggingNoteId,
    notes.setWorkspaceDropTargetParentId,
    handleDeleteNote,
  ])

  const handleNoteChange = useCallback((id: string, contentMd: string) => {
    notes.handleNoteChange(id, contentMd)
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
          const response = await fetch(sseUrl, {
            method: 'GET',
            headers: {
              Authorization: `Bearer ${auth.tokens!.accessToken}`,
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
            <>
              <div className="topbar-divider" />
              <nav className="breadcrumb">
                <span className="breadcrumb-item">{workspaces.currentWorkspace?.name || 'Workspace'}</span>
                <span className="breadcrumb-sep">/</span>
                <span className="breadcrumb-item" style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                  {activeWorkspaceView === 'dashboard' ? 'Dashboard'
                    : activeWorkspaceView === 'records' ? 'Records'
                      : activeWorkspaceView === 'schedule' ? 'Schedule'
                        : (notes.activeWorkspaceNote ? noteTitleFromMd(notes.activeWorkspaceNote.contentMd) : 'Note')}
                </span>
              </nav>
              {auth.tokens && (
                <button
                  type="button"
                  className="topbar-btn topbar-search-btn"
                  onClick={() => setIsSearchOpen(true)}
                  title="Search (Ctrl+K)"
                >
                  <Search size={13} />
                  <span>Search</span>
                  <kbd>⌘ + K</kbd>
                </button>
              )}
            </>
          )}
        </div>

        <div className="topbar-right">
          {auth.tokens && (
            <>
              <button
                type="button"
                className="topbar-btn ask-ai-topbar-btn"
                onClick={() => setIsAskAIOpen(true)}
                title="Ask AI"
              >
                <span style={{ fontSize: 13 }}>✦</span>
                <span>Ask AI</span>
              </button>
              <NotificationBell
                notifications={notifications}
                onMarkRead={(id) => setNotifications(prev => prev.map(n => n.id === id ? { ...n, read: true } : n))}
                onMarkAllRead={() => setNotifications(prev => prev.map(n => ({ ...n, read: true })))}
                onDismiss={(id) => setNotifications(prev => prev.filter(n => n.id !== id))}
              />
              <div className="user-avatar" title={auth.user?.email}>{userInitial}</div>
              <button type="button" className="topbar-btn" onClick={auth.handleLogout} title="Logout">
                <LogOut size={13} />
              </button>
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
          <aside className={`workspace-sidebar ${isWorkspaceSidebarCollapsed ? 'collapsed' : ''}`}>
            <div className='workspace-sidebar-header'>
              <div className="workspace-switcher-container">
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
              <button
                type="button"
                className="workspace-sidebar-toggle"
                onClick={() => setIsWorkspaceSidebarCollapsed((prev) => !prev)}
                aria-label={isWorkspaceSidebarCollapsed ? 'Mở sidebar' : 'Thu sidebar'}
              >
                {isWorkspaceSidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
              </button>
            </div>
            <div className="workspace-sidebar-body">
              {/* GLOBAL SECTION */}
              <div className="sidebar-global-section">
                <button
                  type="button"
                  className={`workspace-sidebar-section-title sidebar-section-toggle ${!routeWorkspaceState.workspaceId ? 'active' : ''}`}
                  onClick={() => navigate('/')}
                >
                  <Home size={15} />
                  <span>Home</span>
                </button>

                <button
                  type="button"
                  className="workspace-sidebar-section-title sidebar-section-toggle"
                  onClick={() => {/* TODO: Navigate to notifications */ }}
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                  <span>Notifications</span>
                </button>
              </div>

              {/* WORKSPACE SECTION */}
              {workspaces.currentWorkspace && (
                <>
                  <div className="sidebar-section-divider" />

                  <div className="sidebar-workspace-section">
                    <button
                      type="button"
                      className={`workspace-sidebar-section-title sidebar-section-toggle  ${activeWorkspaceView === 'schedule' ? 'active' : ''}`}
                      onClick={() => {
                        const workspaceId = workspaces.currentWorkspace?.id
                        if (workspaceId) navigate(workspaceRoute(workspaceId, '/schedule'))
                      }}
                    >
                      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
                        <line x1="16" y1="2" x2="16" y2="6" />
                        <line x1="8" y1="2" x2="8" y2="6" />
                        <line x1="3" y1="10" x2="21" y2="10" />
                      </svg>
                      <span>Schedule</span>
                    </button>

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
                          <div className="workspace-nav-item workspace-nav-item--sub" style={{ color: '#a39e98', fontStyle: 'italic' }}>
                            <span>No notes yet</span>
                          </div>
                        ) : (
                          <>
                            {notes.workspaceRootNotes.map((note) => (
                              <div key={note.id}>
                                <button
                                  type="button"
                                  className={[
                                    'workspace-nav-item',
                                    'workspace-nav-item--sub',
                                    activeWorkspaceView === 'note' && activeWorkspaceNoteId === note.id ? 'active' : '',
                                    notes.workspaceDropTargetParentId === note.id ? 'workspace-nav-item--drop-target' : '',
                                  ].filter(Boolean).join(' ')}
                                  style={{ paddingLeft: '10px' }}
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
                                      className="workspace-nav-action-btn danger"
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
                          className="workspace-nav-item workspace-nav-item--sub workspace-nav-item--add"
                          onClick={() => handleCreateNote()}
                          title="New note"
                        >
                          <Plus size={13} />
                          <span>New note</span>
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
                          <div className="workspace-nav-item workspace-nav-item--sub" >
                            <Video size={13} />
                            <span>Loading...</span>
                          </div>
                        ) : assets.sidebarAssets.length === 0 ? (
                          <div className="workspace-nav-item workspace-nav-item--sub" >
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
                                  className={`workspace-nav-item workspace-nav-item--sub ${activeWorkspaceView === 'records' && activeWorkspaceAssetId === asset.id ? 'active' : ''}`}
                                  onClick={() => {
                                    const workspaceId = workspaces.currentWorkspace?.id
                                    if (workspaceId) navigate(knowledgeRoute(workspaceId, asset.id))
                                  }}
                                  title={displayName}
                                >
                                  <span className="sidebar-section-toggle-chevron"><Video size={13} /></span>
                                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{displayName}</span>
                                  <div className="workspace-nav-item-actions">
                                    <button
                                      type="button"
                                      className="workspace-nav-action-btn danger"
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
                  </div>
                </>
              )}

              {/* SIDEBAR FOOTER */}
              <div className="workspace-sidebar-footer">
                <button
                  type="button"
                  className="workspace-nav-item"
                  onClick={() => navigate('/settings')}
                >
                  <Settings size={15} />
                  <span>Settings</span>
                </button>
              </div>
            </div>
          </aside>

          <div className="workspace-area" style={{ maxWidth: '100%' }}>
            {!routeWorkspaceState.workspaceId ? (
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
                onOpenWorkspace={(workspaceId) => {
                  const workspace = workspaces.workspaces.find(ws => ws.id === workspaceId)
                  if (workspace) handleWorkspaceSwitch(workspace)
                }}
                onOpenNote={(noteId) => openWorkspaceNote(noteId)}
              />
            ) : activeWorkspaceView === 'dashboard' ? (
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
                  onAskAI={() => setIsAskAIOpen(true)}
                  onSelectionChange={(text) => setPendingSelection(text)}
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
                onClose={() => setIsAskAIOpen(false)}
                onInsert={(text) => {
                  if (!notes.activeWorkspaceNote) return
                  const newContent = notes.activeWorkspaceNote.contentMd + '\n\n' + text
                  handleNoteChange(notes.activeWorkspaceNote.id, newContent)
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