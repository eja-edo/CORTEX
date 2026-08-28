/**
 * Route constants for project-centric routing
 * 
 * Route structure:
 * /                          → GlobalHome (user dashboard)
 * /schedule                  → ScheduleView
 * /notifications             → Notifications
 * /settings                  → UserSettings
 * 
 * /p/:projectId            → Project landing (legacy alias for /schedule)
 * /p/:projectId/notes      → NotesList
 * /p/:projectId/notes/:id  → NoteEditor
 * /p/:projectId/records    → RecordsList
 * /p/:projectId/records/:assetId/knowledge → KnowledgeView
 */

export const ROUTES = {
  // Global routes (no project context)
  HOME: '/',
  /** "Hôm nay" — the product's main screen (2.7). */
  TODAY: '/today',
  SCHEDULE: '/schedule',
  /** Tasks dashboard — every task, organised by day/week/month, not just
   * the handful ranked onto "Hôm nay". */
  TASKS: '/tasks',
  NOTIFICATIONS: '/notifications',
  AUTH_CALLBACK: '/auth/callback',

  // Project routes (require projectId)
  PROJECT_BASE: '/p/:projectId',
  PROJECT_NOTES: '/p/:projectId/notes',
  PROJECT_NOTE: '/p/:projectId/notes/:noteId',
  PROJECT_RECORDS: '/p/:projectId/records',
  PROJECT_RECORD_KNOWLEDGE: '/p/:projectId/records/:assetId/knowledge',
  PROJECT_WORKFLOWS: '/p/:projectId/workflows',
  PROJECT_WORKFLOW: '/p/:projectId/workflows/:workflowId',
} as const

export type RoutePath = typeof ROUTES[keyof typeof ROUTES]

/**
 * Every exact pathname that renders without a project.
 *
 * App.tsx redirects anything it doesn't recognise back to `/`, so a route
 * that exists in ROUTES but is missing here is unreachable — you click the
 * nav item and land on the home page. Keeping the two lists in one file (and
 * asserting they agree in routes.spec.ts) is what stops that happening
 * again; it already did once, when /today was added.
 */
export const GLOBAL_ROUTES: readonly string[] = [
  ROUTES.HOME,
  ROUTES.TODAY,
  ROUTES.SCHEDULE,
  ROUTES.TASKS,
  ROUTES.NOTIFICATIONS,
  ROUTES.AUTH_CALLBACK,
  // Not in ROUTES yet — it has no helper and no constant, but the app
  // does render it.
  '/settings',
] as const

/** True for a pathname the app knows how to render. */
export function isKnownRoute(pathname: string): boolean {
  return GLOBAL_ROUTES.includes(pathname) || isProjectRoute(pathname)
}

/**
 * Helper to build project-scoped URLs
 */
export function projectRoute(projectId: string, path: '/notes' | '/records' | '/workflows' | '' = ''): string {
  if (!projectId) {
    console.warn('projectRoute called with empty projectId')
    return '/'
  }
  return `/p/${projectId}${path}`
}

/**
 * Helper to build the global schedule URL
 */
export function scheduleRoute(): string {
  return ROUTES.SCHEDULE
}

/**
 * Helper to build the Tasks dashboard URL.
 */
export function tasksRoute(): string {
  return ROUTES.TASKS
}

/**
 * Helper to build the "Hôm nay" URL. Top-level, not project-scoped —
 * tasks are all personal in Phase 2.
 */
export function todayRoute(): string {
  return ROUTES.TODAY
}

/**
 * Helper to build the Notifications page URL.
 */
export function notificationsRoute(): string {
  return ROUTES.NOTIFICATIONS
}

/**
 * Helper to build note URL within project
 */
export function noteRoute(projectId: string, noteId: string): string {
  if (!projectId || !noteId) {
    console.warn('noteRoute called with empty projectId or noteId')
    return '/'
  }
  return `/p/${projectId}/notes/${noteId}`
}

/**
 * Helper to build knowledge view URL
 */
export function knowledgeRoute(projectId: string, assetId: string): string {
  if (!projectId || !assetId) {
    console.warn('knowledgeRoute called with empty projectId or assetId')
    return '/'
  }
  return `/p/${projectId}/records/${assetId}/knowledge`
}

/**
 * Helper to build workflow URL within project
 */
export function workflowRoute(projectId: string, workflowId?: string): string {
  if (!projectId) {
    console.warn('workflowRoute called with empty projectId')
    return '/'
  }
  if (workflowId) {
    return `/p/${projectId}/workflows/${workflowId}`
  }
  return `/p/${projectId}/workflows`
}

/**
 * Extract projectId from pathname
 */
export function extractProjectId(pathname: string): string | null {
  const match = pathname.match(/^\/w\/([^/]+)/)
  return match ? match[1] : null
}

/**
 * Check if path is a project-scoped route
 */
export function isProjectRoute(pathname: string): boolean {
  return pathname.startsWith('/w/')
}

/**
 * Check if path is a global route (no project context)
 */
export function isGlobalRoute(pathname: string): boolean {
  return pathname === '/'
    || pathname === '/today'
    || pathname === '/schedule'
    || pathname === '/tasks'
    || pathname === '/auth/callback'
    || !pathname.startsWith('/w/')
}
