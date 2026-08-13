import { useCallback, useEffect } from 'react'
import type { Task, TaskPriority } from '../types'
import { useTaskStore } from '../stores/taskStore'

export type TaskStatus = 'pending_confirm' | 'todo' | 'in_progress' | 'done' | 'cancelled' | 'rejected'

/** Same shape `useTaskStore` already holds — kept as its own export so
 * existing imports (`type TaskWire`) don't need to change. */
export type TaskWire = Task

/**
 * Data + actions for the Tasks dashboard.
 *
 * Reads from and writes through `useTaskStore` — the same shared cache
 * `useTodayChecklist`/`useEventChecklist`/`useTaskChecklist` use — so an
 * edit made here (or in a sub-task's detail modal, or the Home widget)
 * shows up everywhere else without an explicit refetch.
 */
export function useTasksPage() {
    const tasks = useTaskStore((state) => state.tasks)
    const isLoading = useTaskStore((state) => state.isLoading)
    const error = useTaskStore((state) => state.error)
    const hasLoaded = useTaskStore((state) => state.hasLoaded)
    const fetchAll = useTaskStore((state) => state.fetchAll)
    const storeCreateTask = useTaskStore((state) => state.createTask)
    const storeUpdateTask = useTaskStore((state) => state.updateTask)
    const storeCompleteTask = useTaskStore((state) => state.completeTask)
    const storeCompleteTaskCascade = useTaskStore((state) => state.completeTaskCascade)
    const storeConfirmTask = useTaskStore((state) => state.confirmTask)
    const storeRejectTask = useTaskStore((state) => state.rejectTask)
    const storeDeleteTask = useTaskStore((state) => state.deleteTask)

    useEffect(() => {
        if (!hasLoaded) void fetchAll()
    }, [hasLoaded, fetchAll])

    const createTask = useCallback(async (input: {
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

    /** The checklist's tick: `done → todo` reopens it, anything live
     * (`todo`/`in_progress`) completes it — same rule `useTodayChecklist`
     * uses, so the same task reads the same way in both places. */
    const toggleTaskDone = useCallback(async (task: TaskWire): Promise<void> => {
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

    const renameTask = useCallback(async (taskId: string, title: string): Promise<void> => {
        const trimmed = title.trim()
        if (!trimmed) return
        await storeUpdateTask(taskId, { title: trimmed })
    }, [storeUpdateTask])

    const setTaskDueDate = useCallback(async (taskId: string, dueDate: string | null): Promise<void> => {
        await storeUpdateTask(taskId, { due_date: dueDate })
    }, [storeUpdateTask])

    /** Priority + description, from the shared `TaskDetailPopover`. */
    const updateTaskDetail = useCallback(async (
        taskId: string,
        patch: { due_date?: string | null; priority?: TaskPriority | null; description?: string | null },
    ): Promise<void> => {
        await storeUpdateTask(taskId, patch)
    }, [storeUpdateTask])

    /** `cancelled → todo` is the one legal way back into the state machine
     * — used by the closed-tasks panel to un-cancel something by mistake. */
    const restoreTask = useCallback(async (taskId: string): Promise<void> => {
        await storeUpdateTask(taskId, { status: 'todo' })
    }, [storeUpdateTask])

    const deleteTask = useCallback(async (taskId: string): Promise<void> => {
        await storeDeleteTask(taskId)
    }, [storeDeleteTask])

    return {
        tasks,
        isLoading,
        error,
        fetchAll,
        createTask,
        confirmTask: storeConfirmTask,
        rejectTask: storeRejectTask,
        toggleTaskDone,
        completeTaskCascade,
        renameTask,
        setTaskDueDate,
        updateTaskDetail,
        restoreTask,
        deleteTask,
    }
}
