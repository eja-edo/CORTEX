import { create } from 'zustand'
import type { Task, TaskPriority, TaskStatus } from '../types'
import { requestWithAuth } from '../services/api'

/** Scope for a write to a checklist task tied to a *recurring* event —
 * see `Task.recurrence_id`. Unlike a Schedule, a task has no
 * `this_and_after`: it doesn't own a recurrence rule, the event does. */
export type TaskEditScope = 'this_only' | 'all'

export type TaskOccurrence = { startTime: string; editScope: TaskEditScope }

function occurrenceQuery(occurrence?: TaskOccurrence): string {
    if (!occurrence) return ''
    const params = new URLSearchParams({
        occurrence_start_time: occurrence.startTime,
        edit_scope: occurrence.editScope,
    })
    return `?${params.toString()}`
}

/**
 * The single source of truth for every screen that reads or writes `Task`
 * rows: the Home "Việc hôm nay" widget (`useTodayChecklist`), the Tasks
 * dashboard (`useTasksPage`), an event's checklist (`useEventChecklist`) and
 * a task's own sub-tasks (`useTaskChecklist`) all read from — and mutate
 * through — this store instead of each keeping an independent `useState`.
 *
 * That used to be four separate `fetch-on-mount` hooks, each with its own
 * copy of the task list. Editing a due date in one screen updated only that
 * screen's copy; a different screen already mounted (another tab, or one
 * that just hadn't remounted) kept showing what it had before, with nothing
 * to tell it otherwise. One shared list, updated in place by whichever
 * screen made the write, means every subscriber re-renders with the same
 * data the instant the request resolves — no cross-view staleness, and no
 * refetch-after-every-mutation round trip either.
 *
 * `GET /tasks` (no filter) already returns every status for the user — see
 * `app/api/tasks.py::get_tasks` — so one fetch is a superset of what the
 * three narrower endpoints (`?status=`, `?related_event_id=`,
 * `?parent_task_id=`) used to be called for. Each hook now does that
 * filtering client-side over this shared array instead.
 */

export type CreateTaskInput = {
    title: string
    description?: string | null
    priority?: TaskPriority | null
    due_date?: string | null
    status?: TaskStatus
    related_event_id?: string | null
    parent_task_id?: string | null
}

export type UpdateTaskInput = Partial<{
    title: string
    status: TaskStatus
    due_date: string | null
    priority: TaskPriority | null
    description: string | null
    related_event_id: string | null
    parent_task_id: string | null
}>

interface TaskStore {
    tasks: Task[]
    isLoading: boolean
    /** Distinguishes "never fetched" from "fetched, turned out empty" — the
     * gate every consuming hook uses to decide whether it needs to trigger
     * the first load itself. */
    hasLoaded: boolean
    error: string | null

    fetchAll: () => Promise<void>
    createTask: (input: CreateTaskInput) => Promise<Task>
    updateTask: (taskId: string, patch: UpdateTaskInput, occurrence?: TaskOccurrence) => Promise<Task>
    completeTask: (taskId: string, occurrence?: TaskOccurrence) => Promise<Task>
    /** Completes a task and every sub-task beneath it, however deep — the
     * confirm-dialog flow for a parent task with its own checklist. Returns
     * every task the backend actually changed so the store can patch each
     * of them in place. */
    completeTaskCascade: (taskId: string) => Promise<Task[]>
    confirmTask: (taskId: string) => Promise<Task>
    rejectTask: (taskId: string) => Promise<Task>
    deleteTask: (taskId: string) => Promise<void>
}

export const useTaskStore = create<TaskStore>((set) => ({
    tasks: [],
    isLoading: false,
    hasLoaded: false,
    error: null,

    fetchAll: async () => {
        set({ isLoading: true, error: null })
        try {
            const tasks = await requestWithAuth<Task[]>('/tasks')
            set({ tasks, isLoading: false, hasLoaded: true })
        } catch (err) {
            set({ error: (err as Error).message, isLoading: false, hasLoaded: true })
        }
    },

    createTask: async (input) => {
        const created = await requestWithAuth<Task>('/tasks', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(input),
        })
        set((state) => ({ tasks: [...state.tasks, created] }))
        return created
    },

    updateTask: async (taskId, patch, occurrence) => {
        const updated = await requestWithAuth<Task>(`/tasks/${taskId}${occurrenceQuery(occurrence)}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(patch),
        })
        // An occurrence-scoped write can return an exception row (a
        // different id than `taskId`, created lazily for this_only) that
        // was never part of the plain list to begin with — nothing to
        // patch in place for it here, the checklist widget re-fetches its
        // own occurrence-resolved view separately.
        set((state) => ({
            tasks: state.tasks.map((task) => (task.id === taskId ? updated : task)),
        }))
        return updated
    },

    completeTask: async (taskId, occurrence) => {
        const updated = await requestWithAuth<Task>(
            `/tasks/${taskId}/complete${occurrenceQuery(occurrence)}`,
            { method: 'POST' },
        )
        set((state) => ({
            tasks: state.tasks.map((task) => (task.id === taskId ? updated : task)),
        }))
        return updated
    },

    completeTaskCascade: async (taskId) => {
        const updated = await requestWithAuth<Task[]>(`/tasks/${taskId}/complete_with_subtasks`, { method: 'POST' })
        const byId = new Map(updated.map((task) => [task.id, task]))
        set((state) => ({
            tasks: state.tasks.map((task) => byId.get(task.id) ?? task),
        }))
        return updated
    },

    confirmTask: async (taskId) => {
        const updated = await requestWithAuth<Task>(`/tasks/${taskId}/confirm`, { method: 'POST' })
        set((state) => ({
            tasks: state.tasks.map((task) => (task.id === taskId ? updated : task)),
        }))
        return updated
    },

    rejectTask: async (taskId) => {
        const updated = await requestWithAuth<Task>(`/tasks/${taskId}/reject`, { method: 'POST' })
        set((state) => ({
            tasks: state.tasks.map((task) => (task.id === taskId ? updated : task)),
        }))
        return updated
    },

    deleteTask: async (taskId) => {
        await requestWithAuth<void>(`/tasks/${taskId}`, { method: 'DELETE' })
        set((state) => ({ tasks: state.tasks.filter((task) => task.id !== taskId) }))
    },
}))
