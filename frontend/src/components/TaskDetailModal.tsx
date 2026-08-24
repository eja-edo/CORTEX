import { useEffect, useRef, useState } from 'react'
import { CalendarDays, Circle, CheckCircle2, Clock3, Plus, Trash2, X, XCircle } from 'lucide-react'
import { clsx } from 'clsx'
import type { Task, TaskPriority, TaskStatus } from '../types'
import type { TaskDetailPatch } from './TaskDetailPopover'
import { PriorityIcon } from './PriorityIcon'
import { PriorityMenu } from './PriorityMenu'
import { priorityLabel } from '../utils/taskPriority'
import { DueDateEditor } from './DueDateEditor'
import { MarkdownField } from './MarkdownField'
import { TaskChecklistRow } from './TaskChecklistRow'
import { SubtaskCreatePanel } from './SubtaskCreatePanel'
import { useTaskChecklist } from '../hooks/useTaskChecklist'
import { useConfirmDialog } from '../hooks/useConfirmDialog'
import { useEscapeToClose } from '../hooks/useEscapeToClose'
import { toggleTaskWithCascade } from '../utils/taskCascade'

const STATUS_META: Record<TaskStatus, { label: string; icon: typeof Circle; color: string }> = {
    pending_confirm: { label: 'Chờ xác nhận', icon: Circle, color: 'var(--text-tertiary)' },
    todo: { label: 'Cần làm', icon: Circle, color: 'var(--text-tertiary)' },
    in_progress: { label: 'Đang làm', icon: Clock3, color: 'var(--yellow, #d97706)' },
    done: { label: 'Xong', icon: CheckCircle2, color: 'var(--green, #16a34a)' },
    cancelled: { label: 'Đã huỷ', icon: XCircle, color: 'var(--text-tertiary)' },
    rejected: { label: 'Đã từ chối', icon: XCircle, color: 'var(--red)' },
}

/**
 * Full-page-style task editor, opened by clicking a task's title. Mirrors
 * a Linear issue page — big borderless title/description on the left, a
 * slim "Properties" list and a checklist of sub-tasks on the right/below —
 * trimmed down to only the fields this app's `Task` actually has (no
 * assignee, labels, project or AI suggestions, so those sections are just
 * absent rather than stubbed out).
 */
export function TaskDetailModal({
    task,
    onRename,
    onUpdateDetail,
    onSetDueDate,
    onToggle,
    onRemove,
    onClose,
}: {
    task: Task
    onRename: (title: string) => Promise<void>
    onUpdateDetail: (patch: TaskDetailPatch) => Promise<void>
    onSetDueDate?: (date: string | null) => Promise<void>
    onToggle: () => void
    onRemove: () => void
    onClose: () => void
}) {
    const [draft, setDraft] = useState(task)
    const [titleInput, setTitleInput] = useState(task.title)
    const [priorityMenuOpen, setPriorityMenuOpen] = useState(false)
    const [addingSubtask, setAddingSubtask] = useState(false)
    const priorityBtnRef = useRef<HTMLButtonElement | null>(null)

    const {
        tasks: subtasks, allTasks, fetchTasks: fetchSubtasks, addTask, toggleTask, completeTaskCascade, removeTask,
        updateTask,
    } = useTaskChecklist(task.id)
    const { confirm, dialog } = useConfirmDialog()
    useEscapeToClose(onClose)

    useEffect(() => {
        setDraft(task)
        setTitleInput(task.title)
    }, [task])

    const commitTitle = async () => {
        const trimmed = titleInput.trim()
        if (trimmed && trimmed !== draft.title) {
            await onRename(trimmed)
            setDraft((d) => ({ ...d, title: trimmed }))
        } else {
            setTitleInput(draft.title)
        }
    }

    const status = STATUS_META[draft.status]
    const StatusIcon = status.icon
    const doneSubtasks = subtasks.filter((t) => t.status === 'done').length

    return (
        <>
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal task-detail-modal" onClick={(e) => e.stopPropagation()}>
                <div className="task-detail-modal-topbar">
                    <button
                        type="button"
                        className="modal-close"
                        onClick={() => { onRemove(); onClose() }}
                        aria-label="Xoá"
                        title="Xoá"
                    >
                        <Trash2 size={15} />
                    </button>
                    <button type="button" className="modal-close" onClick={onClose} aria-label="Đóng">
                        <X size={15} />
                    </button>
                </div>

                <div className="task-detail-modal-body">
                    <div className="task-detail-modal-columns">
                        <div className="task-detail-modal-main">
                            <input
                                className="task-detail-modal-title-input"
                                value={titleInput}
                                aria-label="Tiêu đề"
                                onChange={(e) => setTitleInput(e.target.value)}
                                onBlur={() => void commitTitle()}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') { e.preventDefault(); void commitTitle() }
                                    if (e.key === 'Escape') setTitleInput(draft.title)
                                }}
                            />
                            <MarkdownField
                                className="task-detail-modal-description-input"
                                value={draft.description ?? ''}
                                onChange={(next) => setDraft((d) => ({ ...d, description: next }))}
                                onBlur={() => {
                                    if (draft.description !== task.description) {
                                        void onUpdateDetail({ description: draft.description?.trim() || null })
                                    }
                                }}
                                placeholder="Thêm mô tả…"
                                ariaLabel="Mô tả"
                            />

                            <div className="task-detail-modal-checklist">
                                <div className="task-detail-modal-checklist-header">
                                    <span className="task-detail-modal-sidebar-label">Checklist</span>
                                    {subtasks.length > 0 && (
                                        <span className="task-detail-modal-checklist-count">
                                            {doneSubtasks}/{subtasks.length}
                                        </span>
                                    )}
                                </div>

                                {subtasks.length > 0 && (
                                    <ul className="event-checklist-list">
                                        {subtasks.map((subtask) => (
                                            <TaskChecklistRow
                                                key={subtask.id}
                                                task={subtask}
                                                onToggle={() => void toggleTaskWithCascade({
                                                    task: subtask, allTasks, toggle: toggleTask,
                                                    completeCascade: completeTaskCascade, confirm,
                                                })}
                                                onRename={(title) => updateTask(subtask.id, { title })}
                                                onSetDueDate={(date) => updateTask(subtask.id, { due_date: date })}
                                                onUpdateDetail={(patch) => updateTask(subtask.id, patch)}
                                                onRemove={() => void removeTask(subtask.id)}
                                                onDetailClose={() => void fetchSubtasks()}
                                            />
                                        ))}
                                    </ul>
                                )}

                                {addingSubtask ? (
                                    <SubtaskCreatePanel
                                        onCancel={() => setAddingSubtask(false)}
                                        onCreate={async (input) => {
                                            await addTask(input)
                                            setAddingSubtask(false)
                                        }}
                                    />
                                ) : (
                                    <button
                                        type="button"
                                        className="task-detail-modal-checklist-add"
                                        onClick={() => setAddingSubtask(true)}
                                    >
                                        <Plus size={13} />
                                        <span>Thêm sub-issue</span>
                                    </button>
                                )}
                            </div>
                        </div>

                        <div className="task-detail-modal-sidebar">
                            <div className="task-detail-modal-sidebar-label">Thuộc tính</div>

                            <button type="button" className="task-detail-modal-property" onClick={onToggle}>
                                <StatusIcon size={14} style={{ color: status.color }} />
                                <span>{status.label}</span>
                            </button>

                            <button
                                ref={priorityBtnRef}
                                type="button"
                                className={clsx('task-detail-modal-property', draft.priority && `is-${draft.priority}`)}
                                onClick={() => setPriorityMenuOpen((v) => !v)}
                            >
                                <PriorityIcon priority={draft.priority} size={14} />
                                <span>{priorityLabel(draft.priority) ?? 'Không ưu tiên'}</span>
                            </button>
                            {priorityMenuOpen && (
                                <PriorityMenu
                                    anchorRef={priorityBtnRef}
                                    value={draft.priority}
                                    onSelect={(next: TaskPriority | null) => {
                                        setDraft((d) => ({ ...d, priority: next }))
                                        setPriorityMenuOpen(false)
                                        void onUpdateDetail({ priority: next })
                                    }}
                                    onClose={() => setPriorityMenuOpen(false)}
                                />
                            )}

                            {onSetDueDate && (
                                <div className="task-detail-modal-property">
                                    <CalendarDays size={14} />
                                    <DueDateEditor
                                        value={draft.due_date}
                                        onChange={(next) => {
                                            setDraft((d) => ({ ...d, due_date: next }))
                                            void onSetDueDate(next)
                                        }}
                                        dateClassName="task-detail-modal-property-field"
                                        timeClassName="task-detail-modal-property-field"
                                        toggleClassName="task-detail-modal-property-time-toggle"
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </div>
        </div>
        {dialog}
        </>
    )
}
