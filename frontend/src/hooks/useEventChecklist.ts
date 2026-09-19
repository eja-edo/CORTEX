import { useCallback, useEffect, useState } from 'react'
import type { Task, TaskPriority } from '../types'
import { useTaskStore, type TaskEditScope } from '../stores/taskStore'
import { requestWithAuth } from '../services/api'
import { toLocalDateTimeIso } from '../utils/taskDateBuckets'
import type { PromptEditScope } from './useEditScopeDialog'

/**
 * The checklist inside an event (Milestone 2.6).
 *
 * **Renders tasks as a checklist; never parses a checklist into tasks.**
 *
 * Fetches `GET /calendar/events/{id}/checklist` directly rather than
 * filtering the shared task store's list: a checklist task tied to a
 * *recurring* event can have a per-occurrence exception row (see
 * `Task.recurrence_id`), and those rows are deliberately excluded from the
 * plain `GET /tasks` listing the store holds (they're occurrence-specific,
 * not independent top-level tasks) — so this is the only query that can see
 * them. `occurrenceStartTime` is the currently-open occurrence's
 * `start_time`; it only changes anything when `isRecurring` is true.
 */
export function useEventChecklist(
    eventId: string | null,
    eventEndTime: string | null,
    occurrenceStartTime: string | null,
    isRecurring: boolean,
    promptEditScope: PromptEditScope,
) {
    const [tasks, setTasks] = useState<Task[]>([])
    const [isLoading, setIsLoading] = useState(false)
    const storeCreateTask = useTaskStore((state) => state.createTask)
    const storeUpdateTask = useTaskStore((state) => state.updateTask)
    const storeCompleteTask = useTaskStore((state) => state.completeTask)
    const storeDeleteTask = useTaskStore((state) => state.deleteTask)

    const fetchTasks = useCallback(async (): Promise<void> => {
        if (!eventId) return
        setIsLoading(true)
        try {
            const params = occurrenceStartTime
                ? `?occurrence_start_time=${encodeURIComponent(occurrenceStartTime)}`
                : ''
            const items = await requestWithAuth<Task[]>(`/calendar/events/${eventId}/checklist${params}`)
            setTasks(items)
        } catch (error) {
            console.error('Cannot load event checklist:', error)
        } finally {
            setIsLoading(false)
        }
    }, [eventId, occurrenceStartTime])

    useEffect(() => {
        void Promise.resolve().then(() => fetchTasks())
    }, [fetchTasks])

    /** Asks "just this occurrence, or all?" for a field edit (title, due
     * date, priority, description) on a recurring event's checklist item —
     * completion never asks (see `toggleTask`). Returns null if the user
     * cancels. A task has no `this_and_after` (it doesn't own a recurrence
     * rule, the event does), so the dialog only ever offers `this_only`/
     * `all` — the narrowing below is just satisfying the wider `EditScope`
     * return type. */
    const resolveOccurrenceScope = useCallback(async (
        message: string,
    ): Promise<TaskEditScope | null> => {
        if (!isRecurring || !occurrenceStartTime) return null
        const scope = await promptEditScope({
            title: 'Sự kiện lặp lại',
            message,
            options: [
                { scope: 'this_only', label: 'Chỉ buổi này' },
                { scope: 'all', label: 'Toàn bộ chuỗi lặp' },
            ],
        })
        if (!scope) return null
        return scope === 'all' ? 'all' : 'this_only'
    }, [isRecurring, occurrenceStartTime, promptEditScope])

    /** "+ Add a checklist item" panel submit → task.create. On a recurring
     * event this asks the same "this occurrence, or all?" question a field
     * edit does (see `resolveOccurrenceScope`) before creating — `all`
     * (or a non-recurring event) creates the usual series-wide template;
     * `this_only` creates a row that only ever shows up here (see
     * `Task.original_start_time`'s backend docstring). Returns whether it
     * actually created something, so the caller can leave the "+ Add" panel
     * open (with what the user typed still in it) if they cancelled the
     * prompt instead of silently discarding it. */
    const addTask = useCallback(async (input: {
        title: string
        description?: string | null
        priority?: TaskPriority | null
    }): Promise<boolean> => {
        if (!eventId) return false
        const title = input.title.trim()
        if (!title) return false

        const scope = await resolveOccurrenceScope('Áp dụng mục checklist này cho buổi nào?')
        if (isRecurring && occurrenceStartTime && !scope) return false
        const occurrence = scope && occurrenceStartTime ? { startTime: occurrenceStartTime, editScope: scope } : undefined

        // A series-wide item (recurring event, scope 'all') has no single
        // day to default to — every occurrence has its own. Leave due_date
        // unset here; the backend fills in *this occurrence's* end time on
        // read instead of freezing whichever occurrence happened to be open
        // at creation (see CalendarItemService.get_event_checklist point 4).
        // `this_only`, and a non-recurring event, still default to the one
        // real end time they actually have.
        const defaultsToOneRealDate = !isRecurring || scope === 'this_only'
        await storeCreateTask({
            title,
            description: input.description ?? null,
            priority: input.priority ?? null,
            related_event_id: eventId,
            due_date: defaultsToOneRealDate && eventEndTime ? toLocalDateTimeIso(new Date(eventEndTime)) : null,
        }, occurrence)
        await fetchTasks()
        return true
    }, [eventId, eventEndTime, storeCreateTask, fetchTasks, resolveOccurrenceScope, isRecurring, occurrenceStartTime])

    /** Ticking the box → task.complete (or back to todo when un-ticking).
     * Never asks — always scoped to the occurrence being viewed, silently.
     * Only a field edit (title, due date, priority, description) asks
     * whether it's just this occurrence or the whole series (see
     * `updateTask`). */
    const toggleTask = useCallback(async (task: Task): Promise<void> => {
        const occurrence = isRecurring && occurrenceStartTime
            ? { startTime: occurrenceStartTime, editScope: 'this_only' as const }
            : undefined
        if (task.status === 'done') {
            // done → todo is the legal way back; the state machine refuses
            // done → in_progress, so re-opening lands on todo.
            await storeUpdateTask(task.id, { status: 'todo' }, occurrence)
        } else {
            await storeCompleteTask(task.id, occurrence)
        }
        await fetchTasks()
    }, [storeUpdateTask, storeCompleteTask, isRecurring, occurrenceStartTime, fetchTasks])

    /** Deleting a line → task.delete. A row already scoped to one occurrence
     * (created via `addTask`'s `this_only`, or an event that isn't
     * recurring at all) has nothing else "delete" could mean and just
     * deletes outright. A plain series-wide template on a recurring event
     * asks first: `this_only` hides it from just this occurrence (the
     * template, and every other occurrence, is untouched); `all` deletes
     * the template for real. */
    const removeTask = useCallback(async (taskId: string): Promise<void> => {
        const target = tasks.find((t) => t.id === taskId)
        if (target?.original_start_time) {
            await storeDeleteTask(taskId)
            await fetchTasks()
            return
        }

        const scope = await resolveOccurrenceScope('Xoá mục checklist này cho buổi nào?')
        if (isRecurring && occurrenceStartTime && !scope) return
        const occurrence = scope && occurrenceStartTime ? { startTime: occurrenceStartTime, editScope: scope } : undefined

        await storeDeleteTask(taskId, occurrence)
        await fetchTasks()
    }, [tasks, storeDeleteTask, fetchTasks, resolveOccurrenceScope, isRecurring, occurrenceStartTime])

    /** Clicking a line → the popover's edits (due date, priority, description) */
    const updateTask = useCallback(async (
        taskId: string,
        patch: {
            due_date?: string | null
            priority?: TaskPriority | null
            description?: string | null
            title?: string
        },
    ): Promise<void> => {
        const scope = await resolveOccurrenceScope('Áp dụng thay đổi này cho buổi nào?')
        if (isRecurring && occurrenceStartTime && !scope) return
        const occurrence = scope && occurrenceStartTime ? { startTime: occurrenceStartTime, editScope: scope } : undefined
        await storeUpdateTask(taskId, patch, occurrence)
        await fetchTasks()
    }, [storeUpdateTask, resolveOccurrenceScope, isRecurring, occurrenceStartTime, fetchTasks])

    return { tasks, isLoading, fetchTasks, addTask, toggleTask, removeTask, updateTask }
}
