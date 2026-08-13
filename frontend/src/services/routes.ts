/**
 * Route constants for workspace-centric routing
 * 
 * Route structure:
 * /                          → GlobalHome (user dashboard)
 * /schedule                  → ScheduleView
 * /notifications             → Notifications
 * /settings                  → UserSettings
 * 
 * /w/:workspaceId            → Workspace landing (legacy alias for /schedule)
 * /w/:workspaceId/notes      → NotesList
 * /w/:workspaceId/notes/:id  → NoteEditor
 * /w/:workspaceId/records    → RecordsList
 * /w/:workspaceId/records/:assetId/knowledge → KnowledgeView
 */

export const ROUTES = {
  // Global routes (no workspace context)
  HOME: '/',
  /** "Hôm nay" — the product's main screen (2.7). */
  TODAY: '/today',
  SCHEDULE: '/schedule',
  /** Tasks dashboard — every task, organised by day/week/month, not just
   * the handful ranked onto "Hôm nay". */
  TASKS: '/tasks',
  NOTIFICATIONS: '/notifications',
  AUTH_CALLBACK: '/auth/callback',

  // Workspace routes (require workspaceId)
  WORKSPACE_BASE: '/w/:workspaceId',
  WORKSPACE_NOTES: '/w/:workspaceId/notes',
  WORKSPACE_NOTE: '/w/:workspaceId/notes/:noteId',
  WORKSPACE_RECORDS: '/w/:workspaceId/records',
  WORKSPACE_RECORD_KNOWLEDGE: '/w/:workspaceId/records/:assetId/knowledge',
  WORKSPACE_WORKFLOWS: '/w/:workspaceId/workflows',
  WORKSPACE_WORKFLOW: '/w/:workspaceId/workflows/:workflowId',
} as const

export type RoutePath = typeof ROUTES[keyof typeof ROUTES]

/**
 * Every exact pathname that renders without a workspace.
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
  return GLOBAL_ROUTES.includes(pathname) || isWorkspaceRoute(pathname)
}

/**
 * Helper to build workspace-scoped URLs
 */
export function workspaceRoute(workspaceId: string, path: '/notes' | '/records' | '/workflows' | '' = ''): string {
  if (!workspaceId) {
    console.warn('workspaceRoute called with empty workspaceId')
    return '/'
  }
  return `/w/${workspaceId}${path}`
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
 * Helper to build the "Hôm nay" URL. Top-level, not workspace-scoped —
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
 * Helper to build note URL within workspace
 */
export function noteRoute(workspaceId: string, noteId: string): string {
  if (!workspaceId || !noteId) {
    console.warn('noteRoute called with empty workspaceId or noteId')
    return '/'
  }
  return `/w/${workspaceId}/notes/${noteId}`
}

/**
 * Helper to build knowledge view URL
 */
export function knowledgeRoute(workspaceId: string, assetId: string): string {
  if (!workspaceId || !assetId) {
    console.warn('knowledgeRoute called with empty workspaceId or assetId')
    return '/'
  }
  return `/w/${workspaceId}/records/${assetId}/knowledge`
}

/**
 * Helper to build workflow URL within workspace
 */
export function workflowRoute(workspaceId: string, workflowId?: string): string {
  if (!workspaceId) {
    console.warn('workflowRoute called with empty workspaceId')
    return '/'
  }
  if (workflowId) {
    return `/w/${workspaceId}/workflows/${workflowId}`
  }
  return `/w/${workspaceId}/workflows`
}

/**
 * Extract workspaceId from pathname
 */
export function extractWorkspaceId(pathname: string): string | null {
  const match = pathname.match(/^\/w\/([^/]+)/)
  return match ? match[1] : null
}

/**
 * Check if path is a workspace-scoped route
 */
export function isWorkspaceRoute(pathname: string): boolean {
  return pathname.startsWith('/w/')
}

/**
 * Check if path is a global route (no workspace context)
 */
export function isGlobalRoute(pathname: string): boolean {
  return pathname === '/'
    || pathname === '/today'
    || pathname === '/schedule'
    || pathname === '/tasks'
    || pathname === '/auth/callback'
    || !pathname.startsWith('/w/')
}
