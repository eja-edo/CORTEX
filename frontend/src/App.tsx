import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ChevronDown, Home, ListChecks, Menu, PanelLeftClose, PanelLeftOpen, Plus, Search, Settings, StickyNote, Trash2, Video, X } from 'lucide-react'
import { matchPath, useLocation, useNavigate } from 'react-router-dom'
import 'react-big-calendar/lib/css/react-big-calendar.css'
import './App.css'
import './styles/settings.css'
import './styles/globalHome.css'
import './styles/workspace-settings.css'
import { AuthPanel } from './components/AuthPanel'
import { ScheduleForm } from './components/ScheduleForm'
import { SettingsPanel } from './components/SettingsPanel'
import type { EditScope, Schedule, SyncUpdateEvent } from './types'
import type { AppNotification } from './components/NotificationBell'
import { NotificationBell } from './components/NotificationBell'
import type { NotificationKind } from './components/NotificationBell'
import { UserMenu } from './components/UserMenu'
import { NoteEditorPane } from './components/NoteEditorPane'
import { NoteSearch } from './components/NoteSearch'
import { ProjectSwitcher } from './components/ProjectSwitcher'
import { useProjects } from './hooks/useProjects'
import { GlobalHome } from './components/GlobalHome'
import { AskAI } from './components/AskAI'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useEscapeToClose } from './hooks/useEscapeToClose'
import { useToast } from './hooks/useToast'
import { useConfirmDialog } from './hooks/useConfirmDialog'
import { getStoredTheme, applyThemeToDocument } from './utils/theme'
import type { AppTheme } from './utils/theme'
import { getBlockEditingEnabled, setBlockEditingEnabled } from './utils/noteSettings'
import { useAuth } from './hooks/useAuth'
import { useNotes, noteTitleFromMd } from './hooks/useNotes'
import { useSchedules } from './hooks/useSchedules'
import { useCalendarItems } from './hooks/useCalendarItems'
import { useAssets } from './hooks/useAssets'
import { useWorkflows } from './hooks/useWorkflows'
import { useNotifications } from './hooks/useNotifications'
import { usePreferences } from './hooks/usePreferences'
import { requestWithAuth, getCurrentTokens, setCurrentTokens } from './services/api'
import { strings } from './i18n/strings'
import { ROUTES, extractProjectId, isKnownRoute, noteRoute, knowledgeRoute, notificationsRoute, scheduleRoute, tasksRoute, todayRoute, projectRoute, workflowRoute } from './services/routes'
import { TasksPage } from './components/TasksPage'
import { NotificationsPage } from './components/NotificationsPage'

// Lazy-loaded: each of these pulls in a large dependency (ReactFlow,
// react-big-calendar, video/audio playback, or the block editor) that a
// user who never opens that view still had to download up front. Splitting
// them out cuts the initial bundle a login-only visit pays for.
const CalendarView = lazy(() => import('./components/CalendarView').then(m => ({ default: m.CalendarView })))
const RecordPanel = lazy(() => import('./components/RecordPanel').then(m => ({ default: m.RecordPanel })))
const AssetKnowledgeView = lazy(() => import('./components/AssetKnowledgeView').then(m => ({ default: m.AssetKnowledgeView })))
const WorkflowBuilder = lazy(() => import('./components/WorkflowBuilder').then(m => ({ default: m.WorkflowBuilder })))

const SSE_TAB_APPID_KEY = 'cortex_sse_appid'


type SurfaceView = 'dashboard' | 'note' | 'records' | 'knowledge' | 'schedule' | 'tasks' | 'notifications' | 'settings' | 'workflow'

function getRouteState(pathname: string): {
  view: SurfaceView
  projectId: string | null
  noteId: string | null
  assetId: string | null
  workflowId: string | null
} {
  if (matchPath('/schedule', pathname)) {
    return { view: 'schedule', projectId: null, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/w/:projectId/schedule', pathname)) {
    const wsId = extractProjectId(pathname)
    return { view: 'schedule', projectId: wsId, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/tasks', pathname)) {
    return { view: 'tasks', projectId: null, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/notifications', pathname)) {
    return { view: 'notifications', projectId: null, noteId: null, assetId: null, workflowId: null }
  }

  if (matchPath('/settings', pathname)) {
    return { view: 'settings', projectId: null, noteId: null, assetId: null, workflowId: null }
  }

  const projectId = extractProjectId(pathname)

  if (projectId) {
    const workflowMatch = matchPath('/w/:projectId/workflows/:workflowId', pathname)
    if (workflowMatch?.params.workflowId) {
      return {
        view: 'workflow',
        projectId,
        noteId: null,
        assetId: null,
        workflowId: workflowMatch.params.workflowId
      }
    }

    if (matchPath('/w/:projectId/workflows', pathname)) {
      return { view: 'workflow', projectId, noteId: null, assetId: null, workflowId: null }
    }

    const knowledgeMatch = matchPath('/w/:projectId/records/:assetId/knowledge', pathname)
    if (knowledgeMatch?.params.assetId) {
      return {
        view: 'knowledge',
        projectId,
        noteId: null,
        assetId: knowledgeMatch.params.assetId,
        workflowId: null
      }
    }

    const noteMatch = matchPath('/w/:projectId/notes/:noteId', pathname)
    if (noteMatch?.params.noteId) {
      return {
        view: 'note',
        projectId,
        noteId: noteMatch.params.noteId,
        assetId: null,
        workflowId: null
      }
    }

    if (matchPath('/w/:projectId/records', pathname)) {
      return { view: 'records', projectId, noteId: null, assetId: null, workflowId: null }
    }

    if (matchPath('/w/:projectId', pathname) || matchPath('/w/:projectId/notes', pathname)) {
      return { view: 'dashboard', projectId, noteId: null, assetId: null, workflowId: null }
    }
  }

  return { view: 'dashboard', projectId: null, noteId: null, assetId: null, workflowId: null }
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
    <div className={`sidebar-collapsible-section ${isOpen ? 'is-open' : ''}`}>
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
            <span className="app-sidebar-section-chevron">
              <ChevronDown size={13} />
            </span>
          </>
        )}
      </button>
      {!isCollapsed && (
        <div className="app-sidebar-section-body-wrapper">
          <div
            className={[
              'app-sidebar-section-body',
              sectionBodyClassName ?? '',
            ].filter(Boolean).join(' ')}
            {...sectionBodyRestProps}
          >
            {children}
          </div>
        </div>
      )}
    </div>
  )
}

function App() {
  const navigate = useNavigate()
  const location = useLocation()
  const routeState = useMemo(() => getRouteState(location.pathname), [location.pathname])

  const auth = useAuth()
  // Dự án là container duy nhất: nó nhóm cả việc, ghi chú lẫn bản ghi
  // (DESIGN 11.4).
  const projects = useProjects()
  const notes = useNotes(projects.currentProject, routeState.noteId)
  const schedules = useSchedules()
  // The calendar's unified feed (2.6): schedules + tasks in one shape,
  // over the same visible range the schedule list uses.
  const calendarItems = useCalendarItems(schedules.startDate, schedules.endDate)
  const assets = useAssets(projects.currentProject)
  const sidebarWorkflows = useWorkflows()

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
  const toast = useToast()
  const { confirm, dialog: confirmDialog } = useConfirmDialog()
  const [createEventInitialTimes, setCreateEventInitialTimes] = useState<{ startDate: string; endDate: string } | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(() => {
    try {
      return JSON.parse(localStorage.getItem('cortex_sidebar_collapsed') ?? 'false')
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('cortex_sidebar_collapsed', JSON.stringify(isSidebarCollapsed))
    } catch {
      // ignore storage failures
    }
  }, [isSidebarCollapsed])

  /* auth still owns these two strings; they used to render as in-flow
     `.status-bar` banners that pushed the whole app down and had no dismiss.
     Routing them through the toast channel keeps auth untouched while the
     feedback stops moving the layout. */
  useEffect(() => {
    if (auth.statusMessage && !auth.errorMessage) {
      toast.show({ kind: 'success', message: auth.statusMessage })
    }
  }, [auth.statusMessage, auth.errorMessage, toast])

  useEffect(() => {
    if (auth.errorMessage) {
      toast.show({ kind: 'error', message: auth.errorMessage })
    }
  }, [auth.errorMessage, toast])

  /* Below 700px the sidebar leaves the layout flow and becomes an overlay
     drawer. It used to be plain `display: none` with the only re-open button
     living inside the sidebar itself, which made every nav destination
     unreachable on a phone. */
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false)

  // A drawer that survives navigation would cover the page the user just
  // asked for, so close it whenever the route changes. Done as a
  // render-phase adjustment rather than an effect: React re-runs the render
  // before committing, so the drawer never paints open on the new route, and
  // it avoids the cascading extra render an effect would cause.
  const [navPathAtDrawerOpen, setNavPathAtDrawerOpen] = useState(location.pathname)
  if (navPathAtDrawerOpen !== location.pathname) {
    setNavPathAtDrawerOpen(location.pathname)
    setIsMobileNavOpen(false)
  }

  // Escape closes the drawer — the same way every other overlay in the app
  // behaves, and the WCAG-expected way out of a modal surface.
  useEffect(() => {
    if (!isMobileNavOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsMobileNavOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isMobileNavOpen])

   const [theme, _setTheme] = useState<AppTheme>(getStoredTheme)
  const [reviewProposal, setReviewProposal] = useState<{ noteId: string; proposalId: string } | null>(null)
   const [blockEditingEnabled, _setBlockEditingEnabled] = useState<boolean>(getBlockEditingEnabled)
   const [sectionNoteOpen, setSectionNoteOpen] = useState(true)
   const [sectionRecordOpen, setSectionRecordOpen] = useState(true)
   const notif = useNotifications()
   const preferences = usePreferences()
   const syncToastTimerRef = useRef<number | null>(null)

  const activeView = routeState.view
  const [activeAssetId, setActiveAssetId] = useState<string | null>(routeState.assetId)
  const [activeKnowledgeAssetId, setActiveKnowledgeAssetId] = useState<string | null>(routeState.assetId)
  const [activeWorkflowId, setActiveWorkflowId] = useState<string | null>(routeState.workflowId)

useEffect(() => {
     setActiveAssetId(routeState.assetId)
     setActiveWorkflowId(routeState.workflowId)
     if (routeState.view === 'knowledge') {
       setActiveKnowledgeAssetId(routeState.assetId)
     }
   }, [routeState.assetId, routeState.view, routeState.workflowId])

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
    if (matchPath('/w/:projectId', location.pathname) || matchPath('/w/:projectId/schedule', location.pathname)) {
      navigate(scheduleRoute(), { replace: true })
    }
  }, [location.pathname, navigate])

  // "Hôm nay" no longer has a page of its own — it renders on home. Kept as
  // a redirect rather than deleted so an old bookmark or link still lands
  // somewhere correct instead of on the unknown-route fallback.
  useEffect(() => {
    if (location.pathname === todayRoute()) {
      navigate(ROUTES.HOME, { replace: true })
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
     if (!sectionRecordOpen || !auth.tokens || !projects.currentProject) return
     void assets.loadSidebarAssets()
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [sectionRecordOpen, auth.tokens, projects.currentProject])

   useEffect(() => {
     // Workflow đóng băng: không nạp gì nữa.
   }, [])

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
       return
     }
     void auth.fetchCurrentUser(auth.tokens)
     // Nạp lại theo `auth.tokens`, không chỉ một lần lúc mount: store nạp
     // lần đầu trước khi có token thì `GET /projects` ném "Please login
     // first", `hasLoaded` thành true, và bộ chuyển đứng im ở "Chưa có dự
     // án" cho tới khi tải lại trang. Mọi store khác ở đây đã theo đúng
     // nhịp này rồi.
     void projects.fetchAll()
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
     if (!auth.tokens || activeView !== 'settings') return
     void preferences.fetchPreferences()
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens, activeView])

useEffect(() => {
     // URL mang id container ở segment đầu; nó là id dự án. Mở đúng dự
     // án đó khi người dùng vào bằng link, thay vì để sidebar chỉ một nơi
     // và nội dung chỉ nơi khác.
     if (!routeState.projectId || projects.projects.length === 0) return

     const target = projects.projects.find(p => p.id === routeState.projectId)
     if (target && target.id !== projects.currentProject?.id) {
       projects.setOpenProject(target.id)
     }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [routeState.projectId, projects.projects.length, projects.projects])

useEffect(() => {
     if (!auth.tokens) return
     // Khoá theo **dự án**. Hậu quả nếu quên, và đã từng quên:
     // `fetchNotes` chạy một lần lúc mount khi `currentProject` còn `null`,
     // thoát sớm, rồi không bao giờ chạy lại. Danh sách ghi chú trống
     // mãi mà không có lỗi nào.
     void notes.fetchNotes()
   // eslint-disable-next-line react-hooks/exhaustive-deps
   }, [auth.tokens, projects.currentProject?.id])

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
     if (syncToastTimerRef.current) {
       window.clearTimeout(syncToastTimerRef.current)
     }
     syncToastTimerRef.current = window.setTimeout(() => {
       auth.setStatusMessage('')
       syncToastTimerRef.current = null
     }, 5000)
   }, [auth])

   function formatSyncSummary(event: SyncUpdateEvent): string {
    const created = event.stats.created ?? 0
    const updated = event.stats.updated ?? 0
    const deleted = event.stats.deleted ?? 0
    const skipped = event.stats.skipped ?? 0
    const source = event.source === 'google_calendar' ? 'Google Calendar' : event.source
    return `${source} sync: +${created} / ~${updated} / -${deleted} (skip ${skipped})`
  }


  const openProjectNote = useCallback((noteId: string) => {
    // Route ghi chú mang id dự án ở segment đầu (`/p/:projectId/...`).
    const projectId = projects.currentProject?.id
    if (projectId) {
      navigate(noteRoute(projectId, noteId))
    }
  }, [navigate, projects.currentProject])

  const handleCreateNote = useCallback(async (parentNoteId?: string): Promise<void> => {
    const created = await notes.handleCreateNote(parentNoteId)
    if (created) {
      setSectionNoteOpen(true)
      openProjectNote(created.id)
      auth.setStatusMessage('Note created.')
    } else {
      auth.setErrorMessage('Cannot create note')
    }
  }, [notes, openProjectNote, auth, setSectionNoteOpen])

  const handleDeleteNote = useCallback(async (noteId: string): Promise<void> => {
    const removedIds = await notes.handleDeleteNote(noteId)
    if (removedIds.length > 0) {
      if (routeState.noteId && new Set(removedIds).has(routeState.noteId)) {
        const remaining = notes.recentNotes.filter((n) => !removedIds.includes(n.id))
        const nextId = remaining[0]?.id ?? null
        const projectId = projects.currentProject?.id
        if (activeView === 'note' && projectId) {
          navigate(nextId ? noteRoute(projectId, nextId) : projectRoute(projectId))
        }
      }
      auth.setStatusMessage('Note deleted.')
    } else {
      auth.setErrorMessage('Cannot delete note')
    }
  }, [notes, activeView, navigate, projects.currentProject, auth, routeState.noteId, noteRoute])

  const handleProjectSidebarDrop = useCallback(async (targetParentId: string | null): Promise<void> => {
    await notes.handleProjectSidebarDrop(targetParentId)
  }, [notes])

const renderSidebarNoteTree = useCallback((parentId: string | null, depth: number): React.ReactNode => {
     const childNotes = notes.projectNotesByParent.get(parentId) ?? []
     if (!childNotes.length) return null

     return childNotes.map((note) => (
       <div key={note.id}>
         <div
           role="button"
           tabIndex={0}
        className={[
              'app-sidebar-sub-item',
               activeView === 'note' && routeState.noteId === note.id ? 'active' : '',
               notes.projectDropTargetParentId === note.id ? 'workspace-nav-item--drop-target' : '',
            ].filter(Boolean).join(' ')}
           style={{ paddingLeft: `${10 + (depth * 14)}px` }}
           onClick={() => openProjectNote(note.id)}
           onKeyDown={(e) => {
             if (e.key !== 'Enter' && e.key !== ' ') return
             e.preventDefault()
             openProjectNote(note.id)
           }}
           title={note.title}
           draggable
           onDragStart={(e) => {
             e.dataTransfer.effectAllowed = 'move'
             e.dataTransfer.setData('text/plain', note.id)
             notes.setProjectDraggingNoteId(note.id)
             notes.setProjectDropTargetParentId(null)
           }}
           onDragEnd={() => {
             notes.setProjectDraggingNoteId(null)
             notes.setProjectDropTargetParentId(null)
           }}
           onDragOver={(e) => {
             if (!notes.projectDraggingNoteId || !notes.canMoveProjectNote(notes.projectDraggingNoteId, note.id)) return
             e.preventDefault()
             e.stopPropagation()
             e.dataTransfer.dropEffect = 'move'
             notes.setProjectDropTargetParentId(note.id)
           }}
           onDrop={(e) => {
             e.preventDefault()
             e.stopPropagation()
             void handleProjectSidebarDrop(note.id)
             notes.setProjectDraggingNoteId(null)
             notes.setProjectDropTargetParentId(null)
           }}
         >
           <StickyNote size={13} />
           <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{note.title}</span>
            <div className="workspace-nav-item-actions">
              <button
                type="button"
                className="app-sidebar-sub-action-btn danger"
               title={strings.nav.deleteTitle}
               onClick={(e) => {
                 e.stopPropagation()
                 void (async () => {
                   const ok = await confirm({
                     title: 'Xoá note',
                     message: `Xoá "${note.title || 'Untitled'}"? Các note con cũng sẽ bị xoá.`,
                     confirmLabel: 'Xoá',
                     cancelLabel: 'Huỷ',
                   })
                   if (ok) await handleDeleteNote(note.id)
                 })()
               }}
             >
               <Trash2 size={12} />
             </button>
           </div>
         </div>
         {/* eslint-disable-next-line react-hooks/immutability */}
         {renderSidebarNoteTree(note.id, depth + 1)}
       </div>
     ))
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [notes.projectNotesByParent, activeView, routeState.noteId, notes.projectDropTargetParentId,
        notes.projectDraggingNoteId, notes.canMoveProjectNote])

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
  useEscapeToClose(handleCloseCreateEvent, isCreateEventOpen)

  // `CalendarView` draws its grid entirely from `calendarItems` (the unified
  // schedules+tasks feed), not from `schedules.schedules` — that array only
  // backs the detail modal's lookups. `useSchedules`'s own create/update/
  // toggle/remove handlers refetch `schedules` but have no idea
  // `calendarItems` exists, so without also refetching it here, the grid
  // stayed stale after every edit until the next date-range change or
  // manual refresh. These wrappers are what CalendarView/ScheduleForm
  // actually get passed instead of the raw `schedules.*` handlers.
  const handleCreateSchedule = useCallback(async (
    schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>,
  ): Promise<Schedule | null> => {
    const created = await schedules.handleCreateSchedule(schedule)
    if (created) await calendarItems.fetchItems()
    return created
  }, [schedules, calendarItems])

  const handleUpdateSchedule = useCallback(async (
    item: Schedule,
    patch: Partial<Schedule>,
  ): Promise<boolean> => {
    const ok = await schedules.handleUpdateSchedule(item, patch)
    if (ok) await calendarItems.fetchItems()
    return ok
  }, [schedules, calendarItems])

  const handleToggleScheduleComplete = useCallback(async (item: Schedule): Promise<void> => {
    await schedules.handleToggleComplete(item)
    await calendarItems.fetchItems()
  }, [schedules, calendarItems])

  const handleUpdateScheduleInstance = useCallback(async (
    item: Schedule,
    editScope: EditScope,
    patch: Partial<Schedule>,
  ): Promise<boolean> => {
    const ok = await schedules.handleUpdateScheduleInstance(item, editScope, patch)
    if (ok) await calendarItems.fetchItems()
    return ok
  }, [schedules, calendarItems])

  const handleRemoveSchedule = useCallback(async (id: string): Promise<void> => {
    await schedules.handleRemoveSchedule(id)
    await calendarItems.fetchItems()
  }, [schedules, calendarItems])

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
            attention_log_id?: string | null
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
            attentionLogId: payload.attention_log_id ?? null,
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
          void notif.fetchNotifications()

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

  return (
    <div className="app-shell">
      {/* TOP BAR */}
      <header className="topbar">
        <div className="topbar-left">
          {/* Lives in the topbar, not the sidebar: the drawer's own toggle
              is unreachable once the drawer is closed. Hidden above 700px,
              where the sidebar is always on screen. */}
          {auth.tokens && (
            <button
              type="button"
              className="topbar-nav-toggle"
              onClick={() => setIsMobileNavOpen(true)}
              aria-label="Mở menu điều hướng"
              aria-expanded={isMobileNavOpen}
              aria-controls="app-sidebar"
            >
              <Menu size={20} />
            </button>
          )}
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
                onAccept={notif.handleAccept}
              />
              <button type="button" className="topbar-icon-btn" title="Help">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <circle cx="12" cy="12" r="10" />
                  <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
                  <line x1="12" y1="17" x2="12.01" y2="17" />
                </svg>
              </button>
              <UserMenu
                user={auth.user}
                onOpenSettings={() => navigate('/settings')}
                onLogout={() => void auth.handleLogout()}
              />
            </>
          )}
        </div>
      </header>

      {/* MAIN CONTENT */}
      {!auth.tokens ? (
        <div className="main-layout">
          <AuthPanel onLogin={auth.handleLogin} onRegister={auth.handleRegister} isBusy={auth.isBusy} />
        </div>
      ) : (
        <div className="main-layout">
          {/* Scrim: only rendered on mobile via CSS, and only when open.
              Clicking it dismisses, matching the modal convention. */}
          {isMobileNavOpen && (
            <div
              className="app-sidebar-scrim"
              onClick={() => setIsMobileNavOpen(false)}
              aria-hidden="true"
            />
          )}
          <aside
            id="app-sidebar"
            className={`app-sidebar ${isSidebarCollapsed ? 'collapsed' : ''} ${isMobileNavOpen ? 'is-mobile-open' : ''}`}
          >
            <div className="app-sidebar-profile">
              {/* Bộ chuyển dự án — chọn cái mình đang làm việc bên trong. */}
              <ProjectSwitcher
                projects={projects.projects}
                currentProject={projects.currentProject}
                onSwitch={(project) => projects.setOpenProject(project.id)}
                onCreate={projects.create}
                onRename={projects.rename}
                isCollapsed={isSidebarCollapsed}
              />
            </div>

            <div className="app-sidebar-nav">
                <button
                  type="button"
                  className={`app-sidebar-nav-item ${location.pathname === '/' ? 'active' : ''}`}
                  onClick={() => navigate('/')}
                >
                  <Home size={16} />
                  <span className="app-sidebar-nav-label">{strings.nav.home}</span>
                </button>

                <button
                  type="button"
                  className={`app-sidebar-nav-item ${activeView === 'notifications' ? 'active' : ''}`}
                  onClick={() => navigate(notificationsRoute())}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                    <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                  </svg>
                  <span className="app-sidebar-nav-label">{strings.nav.notifications}</span>
                  {notif.notifications.some((n) => !n.read) && (
                    <span className="app-sidebar-nav-badge" aria-hidden />
                  )}
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
                  <span className="app-sidebar-nav-label">{strings.nav.schedule}</span>
                </button>

                <button
                  type="button"
                  className={`app-sidebar-nav-item ${location.pathname === '/tasks' ? 'active' : ''}`}
                  onClick={() => navigate(tasksRoute())}
                >
                  <ListChecks size={16} />
                  <span className="app-sidebar-nav-label">{strings.nav.tasks}</span>
                </button>
              </div>

            {/* Gác theo dự án (DESIGN 11.4). Đây chính là dòng từng làm cả
                khối Ghi chú/Bản ghi biến mất khi container vắng mặt. */}
            {projects.currentProject && (
              <>
                <div className="app-sidebar-sections">

                  <SidebarSection
                    icon={<StickyNote size={15} />}
                    label={strings.nav.notes}
                    isOpen={sectionNoteOpen}
                    onToggle={() => setSectionNoteOpen(v => !v)}
                    isCollapsed={isSidebarCollapsed}
                    sectionBodyProps={{
                      className: notes.projectDropTargetParentId === null ? 'sidebar-section-body--drop-target' : '',
                      onDragOver: (e) => {
                        if (!notes.projectDraggingNoteId || !notes.canMoveProjectNote(notes.projectDraggingNoteId, null)) return
                        e.preventDefault()
                        e.dataTransfer.dropEffect = 'move'
                        notes.setProjectDropTargetParentId(null)
                      },
                      onDrop: (e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        void handleProjectSidebarDrop(null)
                        notes.setProjectDraggingNoteId(null)
                        notes.setProjectDropTargetParentId(null)
                      },
                      onDragLeave: (e) => {
                        if (!(e.currentTarget as HTMLElement).contains(e.relatedTarget as Node)) {
                          notes.setProjectDropTargetParentId(null)
                        }
                      },
                    }}
                  >
                    <div className="workspace-note-links">
                      {notes.projectRootNotes.length === 0 ? (
                        <div className="app-sidebar-sub-item" style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>
                          <span>{strings.nav.noNotesYet}</span>
                        </div>
                      ) : (
                        <>
                          {notes.projectRootNotes.map((note) => (
                            <div key={note.id}>
                              <div
                                role="button"
                                tabIndex={0}
                                className={[
                                  'app-sidebar-sub-item',
                                  activeView === 'note' && routeState.noteId === note.id ? 'active' : '',
                                  notes.projectDropTargetParentId === note.id ? 'workspace-nav-item--drop-target' : '',
                                ].filter(Boolean).join(' ')}
                                onClick={() => openProjectNote(note.id)}
                                onKeyDown={(e) => {
                                  if (e.key !== 'Enter' && e.key !== ' ') return
                                  e.preventDefault()
                                  openProjectNote(note.id)
                                }}
                                title={note.title}
                                draggable
                                onDragStart={(e) => {
                                  e.dataTransfer.effectAllowed = 'move'
                                  e.dataTransfer.setData('text/plain', note.id)
                                  notes.setProjectDraggingNoteId(note.id)
                                  notes.setProjectDropTargetParentId(null)
                                }}
                                onDragEnd={() => {
                                  notes.setProjectDraggingNoteId(null)
                                  notes.setProjectDropTargetParentId(null)
                                }}
                                onDragOver={(e) => {
                                  if (!notes.projectDraggingNoteId || !notes.canMoveProjectNote(notes.projectDraggingNoteId, note.id)) return
                                  e.preventDefault()
                                  e.stopPropagation()
                                  e.dataTransfer.dropEffect = 'move'
                                  notes.setProjectDropTargetParentId(note.id)
                                }}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  void handleProjectSidebarDrop(note.id)
                                  notes.setProjectDraggingNoteId(null)
                                  notes.setProjectDropTargetParentId(null)
                                }}
                              >
                                <StickyNote size={13} />
                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{note.title}</span>
                                <div className="workspace-nav-item-actions">
                                  <button
                                    type="button"
                                    className="app-sidebar-sub-action-btn danger"
                                    title={strings.nav.deleteTitle}
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      void (async () => {
                                        const ok = await confirm({
                                          title: 'Xoá note',
                                          message: `Xoá "${note.title || 'Untitled'}"? Các note con cũng sẽ bị xoá.`,
                                          confirmLabel: 'Xoá',
                                          cancelLabel: 'Huỷ',
                                        })
                                        if (ok) await handleDeleteNote(note.id)
                                      })()
                                    }}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                              {renderSidebarNoteTree(note.id, 1)}
                            </div>
                          ))}
                        </>
                      )}
                      <button
                        type="button"
                        className="app-sidebar-sub-item app-sidebar-sub-item--add"
                        onClick={() => handleCreateNote(routeState.noteId ?? undefined)}
                        title={routeState.noteId ? strings.nav.addSubNote : strings.nav.newNote}
                      >
                        <Plus size={13} />
                        <span>{routeState.noteId ? strings.nav.addSubNote : strings.nav.newNote}</span>
                      </button>
                    </div>
                  </SidebarSection>

                  <SidebarSection
                    icon={<Video size={15} />}
                    label={strings.nav.records}
                    isOpen={sectionRecordOpen}
                    onToggle={() => {
                      setSectionRecordOpen(v => !v)
                    }}
                    isCollapsed={isSidebarCollapsed}
                    onLabelClick={() => {
                      const projectId = projects.currentProject?.id
                      if (projectId) navigate(projectRoute(projectId, '/records'))
                    }}
                  >
                    <div className="workspace-note-links">
                      {assets.sidebarAssetsLoading ? (
                        <div className="app-sidebar-sub-item" >
                          <Video size={13} />
                          <span>{strings.nav.loading}</span>
                        </div>
                      ) : assets.sidebarAssets.length === 0 ? (
                        <div className="app-sidebar-sub-item" >
                          <Video size={13} />
                          <span>{strings.nav.noRecordings}</span>
                        </div>
                      ) : (
                        <>
                          {assets.sidebarAssets.map(asset => {
                            const displayName = asset.title || asset.id.slice(0, 8)
                            return (
                              <div
                                key={asset.id}
                                role="button"
                                tabIndex={0}
                                className={`app-sidebar-sub-item ${activeView === 'records' && activeAssetId === asset.id ? 'active' : ''}`}
                                onClick={() => {
                                  const projectId = projects.currentProject?.id
                                  if (projectId) navigate(knowledgeRoute(projectId, asset.id))
                                }}
                                onKeyDown={(e) => {
                                  if (e.key !== 'Enter' && e.key !== ' ') return
                                  e.preventDefault()
                                  const projectId = projects.currentProject?.id
                                  if (projectId) navigate(knowledgeRoute(projectId, asset.id))
                                }}
                                title={displayName}
                              >
                                <Video size={13} />
                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{displayName}</span>
                                <div className="workspace-nav-item-actions">
                                  <button
                                    type="button"
                                    className="app-sidebar-sub-action-btn danger"
                                    title={strings.nav.deleteTitle}
                                    onClick={async (e) => {
                                      e.stopPropagation()
                                      const ok = await confirm({
                                        title: 'Xoá bản ghi',
                                        message: `Xoá "${asset.title || 'bản ghi này'}"? Không thể hoàn tác.`,
                                        confirmLabel: 'Xoá',
                                        cancelLabel: 'Huỷ',
                                      })
                                      if (ok) {
                                        const deleted = await assets.deleteAsset(asset.id)
                                        if (deleted) {
                                          void assets.loadSidebarAssets()
                                          toast.show({ message: 'Đã xoá bản ghi.' })
                                        } else {
                                          toast.show({ kind: 'error', message: 'Không xoá được bản ghi. Thử lại sau.' })
                                        }
                                      }
                                    }}
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                            )
                          })}
                        </>
                      )}
                    </div>
                  </SidebarSection>

                  {/* Workflow đã đóng băng — gỡ khỏi sidebar, giữ nguyên
                      route và toàn bộ code (`docs/DESIGN.md` 11.2). Nó là bề
                      mặt cuối còn kéo theo `workspace_id`, và bảng
                      `workflow_definitions` đã không còn trong DB, nên nó
                      không có gì để hiển thị kể cả khi mở bằng URL. */}
                </div>
              </>
            )}

            <div className="app-sidebar-footer">
              <button
                type="button"
                className={`app-sidebar-nav-item ${activeView === 'settings' ? 'active' : ''}`}
                onClick={() => navigate('/settings')}
              >
                <Settings size={16} />
                  <span className="app-sidebar-nav-label">{strings.nav.settings}</span>
              </button>
              <button
                type="button"
                className="app-sidebar-nav-item app-sidebar-collapse-toggle"
                onClick={() => setIsSidebarCollapsed(v => !v)}
                title={isSidebarCollapsed ? 'Mở rộng sidebar' : 'Thu gọn sidebar'}
              >
                {isSidebarCollapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
                <span className="app-sidebar-nav-label">{isSidebarCollapsed ? 'Mở rộng' : 'Thu gọn'}</span>
              </button>
            </div>
          </aside>

          <div className="workspace-area" style={{ maxWidth: '100%' }}>
            {/* Keyed by route so a thrown error from one page does not
               linger as a fallback after navigating to the next one — a
               fresh key remounts the boundary along with the content. */}
            <ErrorBoundary key={location.pathname} label="Nội dung trang">
            <Suspense fallback={<div className="workspace-area-loading">Đang tải…</div>}>
            {activeView === 'settings' ? (
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
                quietHours={preferences.quietHours}
                onSaveQuietHours={preferences.saveQuietHours}
                reasonPreferences={preferences.reasons}
                onToggleReasonPreference={preferences.toggleReason}
                channels={preferences.channels}
                onCreateLinkCode={preferences.createLinkCode}
                onUpdateChannel={preferences.updateChannel}
                onDeleteChannel={preferences.removeChannel}
              />
                        ) : activeView === 'schedule' ? (
              <section className="home-workspace">
                <div className="home-schedule-area">
                  <CalendarView
                    items={calendarItems.items}
                    schedules={schedules.schedules}
                    isGoogleCalendarConnected={Boolean(schedules.googleCalendarStatus?.connected)}
                    startDate={schedules.startDate}
                    endDate={schedules.endDate}
                    onStartDateChange={schedules.setStartDate}
                    onEndDateChange={schedules.setEndDate}
                    onFetch={() => {
                      // Both calls are needed: `onFetch` isn't only fired on
                      // date-range change (where calendarItems' own effect
                      // would already cover it) — CalendarView's manual
                      // refresh button calls it directly too, with the range
                      // unchanged, so calendarItems has to be fetched here
                      // explicitly or that button would silently do nothing
                      // for the grid. The out-of-order-response race this
                      // used to cause is now handled by the request-id guard
                      // inside each hook, not by avoiding the duplicate call.
                      void schedules.fetchSchedules()
                      void calendarItems.fetchItems()
                    }}
                    onOpenCreateEvent={handleOpenCreateEvent}
                    onSlotSelect={handleCalendarSlotSelect}
                    onToggleComplete={handleToggleScheduleComplete}
                    onUpdate={handleUpdateSchedule}
                    onUpdateInstance={handleUpdateScheduleInstance}
                    onRemove={handleRemoveSchedule}
                  />
                </div>
              </section>
            ) : activeView === 'tasks' ? (
              <TasksPage />
            ) : activeView === 'notifications' ? (
              <NotificationsPage
                onNavigate={(path) => navigate(path)}
                onNotificationsChanged={() => void notif.fetchNotifications()}
              />
            ) : activeView === 'workflow' ? (
              <WorkflowBuilder
                projectId={projects.currentProject?.id ?? null}
                workflowId={activeWorkflowId}
                onBack={() => {
                  const projectId = projects.currentProject?.id
                  if (projectId) navigate(workflowRoute(projectId))
                }}
                onNavigate={(wfId) => {
                  const projectId = projects.currentProject?.id
                  if (projectId) navigate(workflowRoute(projectId, wfId))
                }}
                onWorkflowsChanged={() => {
                  const projectId = projects.currentProject?.id
                  if (projectId) void sidebarWorkflows.fetchWorkflows({ project_id: projectId })
                }}
              />
            ) : !routeState.projectId ? (
              <GlobalHome
                user={auth.user}
                projects={projects.projects}
                recentNotes={notes.recentNotes}
                upcomingSchedules={schedules.schedules}
                onCreateProject={() => {
                  const name = window.prompt(strings.projects.newProjectPrompt)?.trim()
                  if (name) void projects.create(name)
                }}
                onOpenProject={(projectId) => {
                  projects.setOpenProject(projectId)
                  navigate(tasksRoute())
                }}
                onOpenNote={(noteId) => openProjectNote(noteId)}
              />
            ) : activeView === 'records' ? (
              <RecordPanel
                requestWithAuth={requestWithAuth}
                isVisible
                initialAssetId={activeAssetId}
                onAssetViewed={() => {
                  const projectId = projects.currentProject?.id
                  if (projectId) {
                    navigate(projectRoute(projectId, '/records'))
                  }
                }}
                projectId={projects.currentProject?.id}
                onAssetChange={() => {
                  void assets.loadSidebarAssets()
                }}
              />
            ) : activeView === 'knowledge' && activeKnowledgeAssetId ? (
              <AssetKnowledgeView
                assetId={activeKnowledgeAssetId}
                requestWithAuth={requestWithAuth}
                onClose={() => {
                  const projectId = projects.currentProject?.id
                  if (projectId) navigate(projectRoute(projectId, '/records'))
                }}
              />
            ) : notes.activeNote ? (
              <div className="workspace-note-page">
                <NoteEditorPane
                  note={notes.activeNote}
                  onChange={handleNoteChange}
                  onTitleChange={handleNoteTitleChange}
                  onAskAI={() => setIsAskAIOpen(true)}
                  onSelectionChange={(text) => setPendingSelection(text)}
                  blockEditingEnabled={blockEditingEnabled}
                  reviewProposal={reviewProposal}
                  onReviewProposalResolved={(noteId) => {
                    setReviewProposal(null)
                    void notes.fetchFullNote(noteId)
                  }}
                />
              </div>
            ) : (
              <section className="workspace-empty-note">
                <p>Chọn một ghi chú từ sidebar để mở.</p>
              </section>
            )}
            </Suspense>
            </ErrorBoundary>
          </div>

          {/* AskAI Side Panel */}
          {auth.tokens && isAskAIOpen && (
            <div className="ask-ai-sidebar">
              <AskAI
                noteContent={notes.activeNote?.contentMd}
                noteTitle={notes.activeNote ? noteTitleFromMd(notes.activeNote.contentMd) : undefined}
                pendingSelection={pendingSelection}
                projectId={projects.currentProject?.id}
                onClose={() => setIsAskAIOpen(false)}
                onInsert={(text) => {
                  if (!notes.activeNote) return
                  const newContent = notes.activeNote.contentMd + '\n\n' + text
                  handleNoteChange(notes.activeNote.id, newContent)
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
                onNoteDiff={(noteId, proposalId) => {
                  setReviewProposal({ noteId, proposalId })
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
            <div className="modal task-detail-modal" onClick={(e) => e.stopPropagation()}>
              <div className="task-detail-modal-topbar">
                <button type="button" className="modal-close" onClick={handleCloseCreateEvent} aria-label="Đóng">
                  <X size={15} />
                </button>
              </div>
              <ScheduleForm
                onCreate={handleCreateSchedule}
                initialTimes={createEventInitialTimes}
                onClose={handleCloseCreateEvent}
              />
            </div>
          </div>
        )
      }

      {
        auth.tokens && isSearchOpen && (
          <NoteSearch
            notes={notes.recentNotes}
            onOpenNote={(noteId) => {
              openProjectNote(noteId)
            }}
            onClose={() => setIsSearchOpen(false)}
          />
        )
      }

      {/* Promise-based confirmations for this component's delete actions.
          Rendered once; it is null until a confirmation is pending. */}
      {confirmDialog}

    </div >
  )
}

export default App