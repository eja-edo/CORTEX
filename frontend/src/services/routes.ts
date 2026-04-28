/**
 * Route constants for workspace-centric routing
 * 
 * Route structure:
 * /                          → GlobalHome (user dashboard)
 * /notifications             → Notifications
 * /settings                  → UserSettings
 * 
 * /w/:workspaceId            → WorkspaceDashboard (or redirect to /w/:id/notes)
 * /w/:workspaceId/notes      → NotesList
 * /w/:workspaceId/notes/:id  → NoteEditor
 * /w/:workspaceId/records    → RecordsList
 * /w/:workspaceId/records/:assetId/knowledge → KnowledgeView
 * /w/:workspaceId/schedule   → ScheduleView
 */

export const ROUTES = {
  // Global routes (no workspace context)
  HOME: '/',
  AUTH_CALLBACK: '/auth/callback',
  
  // Workspace routes (require workspaceId)
  WORKSPACE_BASE: '/w/:workspaceId',
  WORKSPACE_NOTES: '/w/:workspaceId/notes',
  WORKSPACE_NOTE: '/w/:workspaceId/notes/:noteId',
  WORKSPACE_RECORDS: '/w/:workspaceId/records',
  WORKSPACE_RECORD_KNOWLEDGE: '/w/:workspaceId/records/:assetId/knowledge',
  WORKSPACE_SCHEDULE: '/w/:workspaceId/schedule',
} as const

export type RoutePath = typeof ROUTES[keyof typeof ROUTES]

/**
 * Helper to build workspace-scoped URLs
 */
export function workspaceRoute(workspaceId: string, path: '/notes' | '/records' | '/schedule' | '' = ''): string {
  if (!workspaceId) {
    console.warn('workspaceRoute called with empty workspaceId')
    return '/'
  }
  return `/w/${workspaceId}${path}`
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
    || pathname === '/auth/callback'
    || !pathname.startsWith('/w/')
}
