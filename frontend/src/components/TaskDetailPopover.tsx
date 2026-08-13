import type { TaskPriority } from '../types'

/**
 * Shape of a task edit — due date, priority, description. Named after the
 * popover that originally carried it; that UI has since been replaced
 * everywhere (`TaskChecklistRow`'s priority dropdown + `TaskDetailModal`,
 * `EventChecklist` via the same `TaskChecklistRow`) but the type is still
 * the common currency between them and `onUpdateDetail`/`updateTask`.
 */
export type TaskDetailPatch = {
    due_date?: string | null
    priority?: TaskPriority | null
    description?: string | null
}
