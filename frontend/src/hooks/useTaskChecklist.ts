import { useCallback, useEffect, useMemo } from 'react'
import type { Task, TaskPriority } from '../types'
import { useTaskStore } from '../stores/taskStore'

/**
 * A task's own checklist (sub-tasks) — the same `related_event_id` pattern
 * `useEventChecklist` uses for "tasks that belong to an event", here for
 * "tasks that belong to a task". Filters the shared task store
 * (`useTaskStore`) down to `parent_task_id === taskId` and never touches the
 * parent's own fields. Reading from the shared store (rather than its own
 * `GET /tasks?parent_task_id=` fetch) is what makes a sub-task created here
 * show up immediately on "Hôm nay" and the Tasks dashboard too.
 */
export function useTaskChecklist(taskId: string | null) {
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

    const tasks = useMemo(
        () => allTasks.filter((task) => task.parent_task_id === taskId),
        [allTasks, taskId],
    )

    /** The sub-issue creation panel → task.create (parent_task_id = taskId) */
    const addTask = useCallback(async (input: {
        title: string
        description?: string | null
        priority?: TaskPriority | null
    }): Promise<void> => {
        if (!taskId) return
        const title = input.title.trim()
        if (!title) return
        await storeCreateTask({
            title,
            description: input.description ?? null,
            priority: input.priority ?? null,
            parent_task_id: taskId,
        })
    }, [taskId, storeCreateTask])

    const toggleTask = useCallback(async (task: Task): Promise<void> => {
        if (task.status === 'done') {
            await storeUpdateTask(task.id, { status: 'todo' })
        } else {
            await storeCompleteTask(task.id)
        }
    }, [storeUpdateTask, storeCompleteTask])

    /** A sub-task ticked while it still has open sub-tasks of its own,
     * once the user's confirmed "yes, cascade" — see `toggleTaskWithCascade`. */
    const completeTaskCascade = useCallback(async (taskId: string): Promise<void> => {
        await storeCompleteTaskCascade(taskId)
    }, [storeCompleteTaskCascade])

    const removeTask = useCallback(async (subtaskId: string): Promise<void> => {
        await storeDeleteTask(subtaskId)
    }, [storeDeleteTask])

    const updateTask = useCallback(async (
        subtaskId: string,
        patch: {
            due_date?: string | null
            priority?: TaskPriority | null
            description?: string | null
            title?: string
        },
    ): Promise<void> => {
        await storeUpdateTask(subtaskId, patch)
    }, [storeUpdateTask])

    return { tasks, allTasks, isLoading, fetchTasks: fetchAll, addTask, toggleTask, completeTaskCascade, removeTask, updateTask }
}
