export type TaskTreeItem<T> = {
    task: T
    depth: number
    /** Whether this task is the last child among its own siblings — decides
     * whether its own connector line stops at this row (⌐) or continues
     * down to the next sibling (├). */
    isLast: boolean
    /** For each ancestor level from the root down to (but not including)
     * this task's own parent: whether that ancestor still has a sibling
     * after it. True means the vertical guide line for that column must
     * keep running past this row to reach it; false means that branch
     * already ended and the column stays blank here. */
    guides: boolean[]
}

/**
 * Turns a flat task list into tree order — each sub-task immediately
 * follows its parent, with the connector info (`depth`, `isLast`, `guides`)
 * a caller renders as an actual tree (vertical guide lines + an elbow into
 * each row), not just an indent. `TaskChecklistRow` renders one `<li>` per
 * task rather than a nested `<ul>` per level, so the tree is expressed as
 * an ordered flat list with per-row connector state — simpler to render,
 * same visual result.
 *
 * A task whose `parent_task_id` doesn't resolve within the same list (the
 * parent is in a different bucket, filtered out, or done) falls back to
 * root — better than silently dropping it.
 */
export function flattenTaskTree<T extends { id: string; parent_task_id: string | null }>(
    tasks: T[],
): TaskTreeItem<T>[] {
    const idsInList = new Set(tasks.map((t) => t.id))
    const childrenByParent = new Map<string, T[]>()

    for (const task of tasks) {
        const parentKey = task.parent_task_id && idsInList.has(task.parent_task_id)
            ? task.parent_task_id
            : 'root'
        const siblings = childrenByParent.get(parentKey)
        if (siblings) siblings.push(task)
        else childrenByParent.set(parentKey, [task])
    }

    const ordered: TaskTreeItem<T>[] = []
    const visit = (parentKey: string, depth: number, ancestorGuides: boolean[]) => {
        const siblings = childrenByParent.get(parentKey) ?? []
        siblings.forEach((task, index) => {
            const isLast = index === siblings.length - 1
            ordered.push({ task, depth, isLast, guides: ancestorGuides })
            if (childrenByParent.has(task.id)) {
                visit(task.id, depth + 1, [...ancestorGuides, !isLast])
            }
        })
    }
    visit('root', 0, [])
    return ordered
}
