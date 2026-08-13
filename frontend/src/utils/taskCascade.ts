/**
 * Shared by every checklist surface (Home widget, Tasks dashboard, a task's
 * own sub-task list) for the "tick a parent that has its own checklist"
 * flow: ask whether every sub-task is really done before completing it,
 * rather than either silently ignoring the checklist or silently finishing
 * it. One copy of the decision so the three surfaces can't drift apart on
 * when they ask.
 */

type TreeNode = { id: string; parent_task_id: string | null; status: string }

const CLOSED_STATUSES = new Set(['done', 'cancelled', 'rejected'])

/**
 * Whether `taskId` has any descendant (child, grandchild, …) that isn't yet
 * closed. Walks the *whole* task list, not just whatever subset happens to
 * be on screen — a sub-task due next week wouldn't be in "today"'s list but
 * still needs asking about.
 */
export function hasIncompleteDescendants(tasks: TreeNode[], taskId: string): boolean {
    const childrenByParent = new Map<string, TreeNode[]>()
    for (const task of tasks) {
        if (task.parent_task_id === null) continue
        const siblings = childrenByParent.get(task.parent_task_id)
        if (siblings) siblings.push(task)
        else childrenByParent.set(task.parent_task_id, [task])
    }

    const stack = [taskId]
    while (stack.length > 0) {
        const currentId = stack.pop() as string
        for (const child of childrenByParent.get(currentId) ?? []) {
            if (!CLOSED_STATUSES.has(child.status)) return true
            stack.push(child.id)
        }
    }
    return false
}

export type ConfirmPrompt = (options: {
    title: string
    message: string
    confirmLabel: string
    cancelLabel: string
}) => Promise<boolean>

/**
 * The tick handler every checklist row should call. `done → todo` (or
 * ticking a task with no open sub-tasks) just toggles that one task. Ticking
 * a task that still has open sub-tasks asks first — "yes" cascades `done` to
 * all of them (however deeply nested), "no"/dismiss completes only the task
 * that was actually clicked.
 */
export async function toggleTaskWithCascade<T extends TreeNode>(params: {
    task: T
    allTasks: TreeNode[]
    toggle: (task: T) => Promise<void>
    completeCascade: (taskId: string) => Promise<void>
    confirm: ConfirmPrompt
}): Promise<void> {
    const { task, allTasks, toggle, completeCascade, confirm } = params

    if (task.status !== 'done' && hasIncompleteDescendants(allTasks, task.id)) {
        const cascadeAll = await confirm({
            title: 'Hoàn thành việc con?',
            message: 'Bạn đã hoàn thành xong tất cả các việc con của mục này chưa?',
            confirmLabel: 'Đã xong hết, đánh dấu tất cả',
            cancelLabel: 'Chỉ việc này',
        })
        if (cascadeAll) {
            await completeCascade(task.id)
            return
        }
    }

    await toggle(task)
}
