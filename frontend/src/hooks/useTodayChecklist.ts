import { useCallback, useEffect, useMemo } from 'react'
import type { TaskPriority, TaskStatus } from '../types'
import { useTaskStore } from '../stores/taskStore'
import { compareByDueDateThenPriority, selectTodayTasks } from '../utils/taskDateBuckets'

/**
 * Today's tasks — overdue, due today, or undated, and not yet closed —
 * plain and manageable: tick it, rename it, change the date or priority,
 * delete it. Renders on the home page's "Việc hôm nay" card.
 *
 * Built from `selectTodayTasks`, the exact same selection the Tasks
 * dashboard's "Hôm nay" day view uses — including event-linked tasks and
 * sub-tasks, which this card used to leave out. That exclusion predated the
 * shared `useTaskStore`: with two independent copies of the task list, an
 * event-linked task showing up in both this card and the event's own
 * checklist meant two edit surfaces racing each other. Now both surfaces
 * write through the same store, so there's exactly one copy to race with
 * itself — and a different selection here than on the Tasks dashboard was
 * the actual bug users kept noticing ("2 nơi không khớp nhau"), not a
 * feature.
 *
 * Reads from and writes through `useTaskStore` — the shared cache every
 * task screen uses — rather than keeping its own copy, so a due date set
 * here shows up immediately on the Tasks dashboard and vice versa.
 */
export function useTodayChecklist() {
    const allTasks = useTaskStore((state) => state.tasks)
    const isLoading = useTaskStore((state) => state.isLoading)
    const hasLoaded = useTaskStore((state) => state.hasLoaded)
    const fetchAll = useTaskStore((state) => state.fetchAll)
    const storeCreateTask = useTaskStore((state) => state.createTask)
    const storeUpdateTask = useTaskStore((state) => state.updateTask)
    const storeCompleteTask = useTaskStore((state) => state.completeTask)
    const storeCompleteTaskCascade = useTaskStore((state) => state.completeTaskCascade)
    const storeDeleteTask = useTaskStore((state) => state.deleteTask)

    useEffect(() => {
        if (!hasLoaded) void fetchAll()
    }, [hasLoaded, fetchAll])

    const tasks = useMemo(() => {
        const today = selectTodayTasks(allTasks)
        today.sort((a, b) => {
            const byDueAndPriority = compareByDueDateThenPriority(a, b)
            if (byDueAndPriority !== 0) return byDueAndPriority
            return a.created_at.localeCompare(b.created_at)
        })
        return today
    }, [allTasks])

    /** "+ Add a task" panel submit → task.create. Due date isn't set here —
     * same as a sub-issue, it's set afterwards via the row's own due-date
     * button. */
    const addTask = useCallback(async (input: {
        title: string
        description?: string | null
        priority?: TaskPriority | null
    }): Promise<void> => {
        const title = input.title.trim()
        if (!title) return
        await storeCreateTask({
            title,
            description: input.description ?? null,
            priority: input.priority ?? null,
        })
    }, [storeCreateTask])

    /** Ticking the box → task.complete (done → todo is the legal way back). */
    const toggleTask = useCallback(async (task: { id: string; status: TaskStatus }): Promise<void> => {
        if (task.status === 'done') {
            await storeUpdateTask(task.id, { status: 'todo' })
        } else {
            await storeCompleteTask(task.id)
        }
    }, [storeUpdateTask, storeCompleteTask])

    /** Ticking a task that still has open sub-tasks, once the user's
     * confirmed "yes, cascade" — see `toggleTaskWithCascade`. */
    const completeTaskCascade = useCallback(async (taskId: string): Promise<void> => {
        await storeCompleteTaskCascade(taskId)
    }, [storeCompleteTaskCascade])

    /** Editing the title inline. */
    const renameTask = useCallback(async (taskId: string, title: string): Promise<void> => {
        const trimmed = title.trim()
        if (!trimmed) return
        await storeUpdateTask(taskId, { title: trimmed })
    }, [storeUpdateTask])

    /** Setting or clearing the due date. */
    const setDueDate = useCallback(async (taskId: string, dueDate: string | null): Promise<void> => {
        await storeUpdateTask(taskId, { due_date: dueDate })
    }, [storeUpdateTask])

    /** Priority + description, from the shared `TaskDetailPopover`. */
    const updateTaskDetail = useCallback(async (
        taskId: string,
        patch: { due_date?: string | null; priority?: TaskPriority | null; description?: string | null },
    ): Promise<void> => {
        await storeUpdateTask(taskId, patch)
    }, [storeUpdateTask])

    /** Deleting a line → task.delete. */
    const removeTask = useCallback(async (taskId: string): Promise<void> => {
        await storeDeleteTask(taskId)
    }, [storeDeleteTask])

    return {
        tasks, allTasks, isLoading, fetchTasks: fetchAll, addTask, toggleTask, completeTaskCascade, renameTask,
        setDueDate, updateTaskDetail, removeTask,
    }
}
