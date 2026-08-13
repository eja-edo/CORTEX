import { useState } from 'react'
import { Plus } from 'lucide-react'
import { useTodayChecklist } from '../hooks/useTodayChecklist'
import { useConfirmDialog } from '../hooks/useConfirmDialog'
import { TaskChecklistRow } from './TaskChecklistRow'
import { SubtaskCreatePanel } from './SubtaskCreatePanel'
import { flattenTaskTree } from '../utils/taskTree'
import { toggleTaskWithCascade } from '../utils/taskCascade'

/**
 * Full CRUD checklist of today's open work. Renders inside the "Việc hôm
 * nay" card on the home page's right column: every open task the user has,
 * plain and manageable — tick it, rename it, change the date or priority,
 * delete it.
 */
export function TodayChecklist() {
    const {
        tasks, allTasks, isLoading, fetchTasks, addTask, toggleTask, completeTaskCascade, renameTask, setDueDate,
        updateTaskDetail, removeTask,
    } = useTodayChecklist()
    const [addingTask, setAddingTask] = useState(false)
    const { confirm, dialog } = useConfirmDialog()

    if (isLoading && tasks.length === 0) {
        return null
    }

    const doneCount = tasks.filter((t) => t.status === 'done').length

    return (
        <>
            <section className="today-checklist">
                <div className="today-checklist-header">
                    <span className="today-section-label">Việc hôm nay</span>
                    {tasks.length > 0 && (
                        <span className="today-checklist-count">
                            {doneCount}/{tasks.length}
                        </span>
                    )}
                </div>

                {tasks.length === 0 ? (
                    <p className="today-checklist-empty">Chưa có việc nào ngoài danh sách trên.</p>
                ) : (
                    <ul className="today-checklist-list">
                        {flattenTaskTree(tasks).map(({ task, depth, isLast, guides }) => (
                            <TaskChecklistRow
                                key={task.id}
                                task={task}
                                depth={depth}
                                isLast={isLast}
                                guides={guides}
                                onToggle={() => void toggleTaskWithCascade({
                                    task, allTasks, toggle: toggleTask, completeCascade: completeTaskCascade, confirm,
                                })}
                                onRename={(title) => renameTask(task.id, title)}
                                onSetDueDate={(date) => setDueDate(task.id, date)}
                                onUpdateDetail={(patch) => updateTaskDetail(task.id, patch)}
                                onRemove={() => void removeTask(task.id)}
                                onDetailClose={() => void fetchTasks()}
                            />
                        ))}
                    </ul>
                )}

                {addingTask ? (
                    <SubtaskCreatePanel
                        onCancel={() => setAddingTask(false)}
                        onCreate={async (input) => {
                            await addTask(input)
                            setAddingTask(false)
                        }}
                    />
                ) : (
                    <button
                        type="button"
                        className="task-detail-modal-checklist-add"
                        onClick={() => setAddingTask(true)}
                    >
                        <Plus size={13} />
                        <span>Thêm việc</span>
                    </button>
                )}
            </section>
            {dialog}
        </>
    )
}
