import { useCallback, useEffect, useMemo } from 'react'
import type { Task, TaskPriority } from '../types'
import { useTaskStore } from '../stores/taskStore'
import { toLocalDateTimeIso } from '../utils/taskDateBuckets'

/**
 * The checklist inside an event (Milestone 2.6).
 *
 * **Renders tasks as a checklist; never parses a checklist into tasks.**
 *
 * There is no markdown parser here, no diffing of edited lines, and nothing
 * to reconcile. Every user action is one command against one task, and the
 * shared task store (`useTaskStore`) is updated in place — the same store
 * `useTodayChecklist`/`useTasksPage`/`useTaskChecklist` read, so a checklist
 * item created or edited here shows up on "Hôm nay" and the Tasks dashboard
 * immediately, no refetch race. The reverse design — storing checklist text
 * in the event's `description` and syncing it back — needs a diff on every
 * keystroke, and one missed line leaves an orphan task that the Attention
 * Gate will then nag the user about. It also can't carry a due date, a
 * status, a priority or a description without inventing a markdown DSL,
 * and it has no answer
 * at all for tasks created by the AI planner, conversation extraction or a
 * workflow, none of which write a line of markdown.
 */
export function useEventChecklist(eventId: string | null, eventEndTime: string | null) {
    const allTasks = useTaskStore((state) => state.tasks)
    const isLoading = useTaskStore((state) => state.isLoading)
    const hasLoaded = useTaskStore((state) => state.hasLoaded)
    const fetchAll = useTaskStore((state) => state.fetchAll)
    const storeCreateTask = useTaskStore((state) => state.createTask)
    const storeUpdateTask = useTaskStore((state) => state.updateTask)
    const storeCompleteTask = useTaskStore((state) => state.completeTask)
    const storeDeleteTask = useTaskStore((state) => state.deleteTask)

    useEffect(() => {
        if (!hasLoaded) void fetchAll()
    }, [hasLoaded, fetchAll])

    const tasks = useMemo(
        () => allTasks.filter((task) => task.related_event_id === eventId),
        [allTasks, eventId],
    )

    /** "+ Add a checklist item" panel submit → task.create */
    const addTask = useCallback(async (input: {
        title: string
        description?: string | null
        priority?: TaskPriority | null
    }): Promise<void> => {
        if (!eventId) return
        const title = input.title.trim()
        if (!title) return
        await storeCreateTask({
            title,
            description: input.description ?? null,
            priority: input.priority ?? null,
            related_event_id: eventId,
            // Default a checklist item's deadline to the event's own end
            // time, time-of-day included — it belongs to this event, so
            // "done by" defaults to "done by the moment the event ends".
            // Sent as the user's local wall-clock time, not the raw
            // (timezone-bearing) event value: `due_date` has no timezone of
            // its own (see `models.Task.due_date`) — it's "3pm my time", not
            // a UTC instant. Editable afterwards like any other due date
            // (the UI's date picker drops the time).
            due_date: eventEndTime ? toLocalDateTimeIso(new Date(eventEndTime)) : null,
        })
    }, [eventId, eventEndTime, storeCreateTask])

    /** Ticking the box → task.complete (or back to todo when un-ticking) */
    const toggleTask = useCallback(async (task: Task): Promise<void> => {
        if (task.status === 'done') {
            // done → todo is the legal way back; the state machine refuses
            // done → in_progress, so re-opening lands on todo.
            await storeUpdateTask(task.id, { status: 'todo' })
        } else {
            await storeCompleteTask(task.id)
        }
    }, [storeUpdateTask, storeCompleteTask])

    /** Deleting a line → task.delete */
    const removeTask = useCallback(async (taskId: string): Promise<void> => {
        await storeDeleteTask(taskId)
    }, [storeDeleteTask])

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
        await storeUpdateTask(taskId, patch)
    }, [storeUpdateTask])

    return { tasks, isLoading, fetchTasks: fetchAll, addTask, toggleTask, removeTask, updateTask }
}
