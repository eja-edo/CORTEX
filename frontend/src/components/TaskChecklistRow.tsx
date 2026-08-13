import { useRef, useState } from 'react'
import { Check, CalendarDays, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'
import type { Task } from '../types'
import { PriorityIcon } from './PriorityIcon'
import { PriorityMenu } from './PriorityMenu'
import { TaskDetailModal } from './TaskDetailModal'
import type { TaskDetailPatch } from './TaskDetailPopover'
import { priorityLabel } from '../utils/taskPriority'
import { dateOnly, formatCompactDate, isTaskOverdue } from '../utils/taskDateBuckets'
import { DueDateEditor, timePartOf } from './DueDateEditor'

/**
 * One checklist line: tick to complete (dims + strikes through), click the
 * priority glyph for a quick priority change, click the date to change it,
 * click the title to open the task's detail view.
 *
 * Extracted from `TodayChecklist.tsx` so the same interaction — and the same
 * `.today-checklist-*` styling — is available wherever a plain, editable
 * task list shows up (originally only "Hôm nay"; now also the Tasks
 * dashboard's day/week/month views).
 */
export function TaskChecklistRow({
    task,
    onToggle,
    onRename,
    onSetDueDate,
    onUpdateDetail,
    onRemove,
    onDetailClose,
    showDate = true,
    depth = 0,
    isLast = true,
    guides = [],
}: {
    task: Task
    onToggle: () => void
    onRename: (title: string) => Promise<void>
    onSetDueDate?: (date: string | null) => Promise<void>
    /** Priority quick-pick and detail-view edits. Omit to hide the priority
     * glyph entirely (e.g. a read-only context). */
    onUpdateDetail?: (patch: TaskDetailPatch) => Promise<void>
    onRemove: () => void
    /** Fired when the detail modal closes. The modal can create/edit its
     * own sub-tasks (a `useTaskChecklist` instance the list this row lives
     * in knows nothing about) — without this, a sub-task added there never
     * shows up here until the page is reloaded. */
    onDetailClose?: () => void
    /** Week/month boxes already show the date via which box the row sits
     * in, so repeating it on every row would be noise. */
    showDate?: boolean
    /** Tree connector state from `flattenTaskTree` — how many levels deep
     * this task is (0 for a top-level task), whether it's the last child
     * among its own siblings, and for each ancestor level whether that
     * branch's vertical guide line still needs to run past this row. */
    depth?: number
    isLast?: boolean
    guides?: boolean[]
}) {
    const [editingDate, setEditingDate] = useState(false)
    const [priorityMenuOpen, setPriorityMenuOpen] = useState(false)
    const [detailOpen, setDetailOpen] = useState(false)
    const priorityBtnRef = useRef<HTMLButtonElement | null>(null)

    const isDone = task.status === 'done'
    const isOverdue = isTaskOverdue(task)

    return (
        <li className={clsx('today-checklist-row', isDone && 'is-done', isOverdue && 'is-overdue')}>
            {depth > 0 && (
                <span className="today-checklist-tree" aria-hidden>
                    {guides.slice(1).map((open, i) => (
                        <span key={i} className={clsx('today-checklist-guide', open && 'is-open')} />
                    ))}
                    <span
                        className={clsx('today-checklist-guide today-checklist-guide-elbow', !isLast && 'is-open')}
                    />
                </span>
            )}
            <button
                type="button"
                className="today-checklist-box"
                role="checkbox"
                aria-checked={isDone}
                aria-label={isDone ? 'Bỏ đánh dấu xong' : 'Đánh dấu xong'}
                onClick={onToggle}
            >
                {isDone && <Check size={12} />}
            </button>

            {onUpdateDetail && (
                <>
                    <button
                        ref={priorityBtnRef}
                        type="button"
                        className={clsx('today-checklist-priority', task.priority && `is-${task.priority}`)}
                        aria-label="Ưu tiên"
                        title={priorityLabel(task.priority) ?? 'Đặt ưu tiên'}
                        onClick={() => setPriorityMenuOpen((v) => !v)}
                    >
                        <PriorityIcon priority={task.priority} />
                    </button>
                    {priorityMenuOpen && (
                        <PriorityMenu
                            anchorRef={priorityBtnRef}
                            value={task.priority}
                            onSelect={(priority) => {
                                setPriorityMenuOpen(false)
                                void onUpdateDetail({ priority })
                            }}
                            onClose={() => setPriorityMenuOpen(false)}
                        />
                    )}
                </>
            )}

            <button
                type="button"
                className="today-checklist-title"
                onClick={() => setDetailOpen(true)}
                title="Xem chi tiết"
            >
                {task.title}
            </button>

            {showDate && onSetDueDate && (
                editingDate ? (
                    <span
                        className="today-checklist-date-editor"
                        onBlur={(e) => {
                            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                                setEditingDate(false)
                            }
                        }}
                    >
                        <DueDateEditor
                            value={task.due_date}
                            onChange={(next) => void onSetDueDate(next)}
                            autoFocus
                            dateClassName="today-checklist-date-input"
                            timeClassName="today-checklist-date-input"
                            toggleClassName="today-checklist-date-time-toggle"
                        />
                    </span>
                ) : (
                    <span className="today-checklist-date-wrap">
                        <button
                            type="button"
                            className={clsx('today-checklist-date', isOverdue && 'is-overdue')}
                            onClick={() => setEditingDate(true)}
                            title={isOverdue ? 'Đã quá hạn' : 'Đặt hạn'}
                        >
                            <CalendarDays size={11} />
                            {task.due_date
                                ? `${formatCompactDate(dateOnly(task.due_date))}${timePartOf(task.due_date) ? `, ${timePartOf(task.due_date)}` : ''}`
                                : 'hạn?'}
                        </button>
                        {task.due_date && (
                            <button
                                type="button"
                                className="today-checklist-date-clear"
                                aria-label="Bỏ hạn"
                                title="Bỏ hạn"
                                onClick={() => void onSetDueDate(null)}
                            >
                                <X size={9} />
                            </button>
                        )}
                    </span>
                )
            )}

            <button
                type="button"
                className="today-checklist-remove"
                aria-label={`Xoá: ${task.title}`}
                onClick={onRemove}
            >
                <Trash2 size={12} />
            </button>

            {detailOpen && onUpdateDetail && (
                <TaskDetailModal
                    task={task}
                    onRename={onRename}
                    onUpdateDetail={onUpdateDetail}
                    onSetDueDate={onSetDueDate}
                    onToggle={onToggle}
                    onRemove={onRemove}
                    onClose={() => {
                        setDetailOpen(false)
                        onDetailClose?.()
                    }}
                />
            )}
        </li>
    )
}
