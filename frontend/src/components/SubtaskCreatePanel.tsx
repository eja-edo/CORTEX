import { useEffect, useRef, useState } from 'react'
import { Circle } from 'lucide-react'
import { clsx } from 'clsx'
import type { TaskPriority } from '../types'
import { PriorityIcon } from './PriorityIcon'
import { PriorityMenu } from './PriorityMenu'
import { priorityLabel } from '../utils/taskPriority'

/**
 * The "+ Add sub-issues" inline creation form — Linear's panel trimmed to
 * the fields this app's `Task` actually has. The reference has a project
 * badge, an assignee pill, a labels pill and an AI "quick suggestions"
 * chip; none of those exist here (no project/assignee/label concept, no
 * suggestion feature), so only title, description and priority remain.
 */
export function SubtaskCreatePanel({
    onCancel,
    onCreate,
}: {
    onCancel: () => void
    onCreate: (input: { title: string; description: string | null; priority: TaskPriority | null }) => Promise<void>
}) {
    const [title, setTitle] = useState('')
    const [description, setDescription] = useState('')
    const [priority, setPriority] = useState<TaskPriority | null>(null)
    const [priorityMenuOpen, setPriorityMenuOpen] = useState(false)
    const [isSubmitting, setIsSubmitting] = useState(false)
    const titleRef = useRef<HTMLInputElement | null>(null)
    const priorityBtnRef = useRef<HTMLButtonElement | null>(null)

    useEffect(() => {
        titleRef.current?.focus()
    }, [])

    const submit = async () => {
        if (!title.trim() || isSubmitting) return
        setIsSubmitting(true)
        try {
            await onCreate({ title: title.trim(), description: description.trim() || null, priority })
        } finally {
            setIsSubmitting(false)
        }
    }

    return (
        <div className="subtask-create-panel" onClick={(e) => e.stopPropagation()}>
            <div className="subtask-create-row">
                <Circle size={14} className="subtask-create-checkbox" />
                <input
                    ref={titleRef}
                    className="subtask-create-title"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Tiêu đề"
                    aria-label="Tiêu đề"
                    onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void submit() }
                        if (e.key === 'Escape') onCancel()
                    }}
                />
            </div>
            <textarea
                className="subtask-create-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Thêm mô tả…"
                aria-label="Mô tả"
                rows={2}
            />
            <div className="subtask-create-footer">
                <button
                    ref={priorityBtnRef}
                    type="button"
                    className={clsx('subtask-create-priority', priority && `is-${priority}`)}
                    onClick={() => setPriorityMenuOpen((v) => !v)}
                >
                    <PriorityIcon priority={priority} size={13} />
                    <span>{priorityLabel(priority) ?? 'Không ưu tiên'}</span>
                </button>
                {priorityMenuOpen && (
                    <PriorityMenu
                        anchorRef={priorityBtnRef}
                        value={priority}
                        onSelect={(next) => {
                            setPriority(next)
                            setPriorityMenuOpen(false)
                        }}
                        onClose={() => setPriorityMenuOpen(false)}
                    />
                )}

                <div className="subtask-create-actions">
                    <button type="button" className="btn btn-ghost" onClick={onCancel}>
                        Huỷ
                    </button>
                    <button
                        type="button"
                        className="btn btn-primary"
                        disabled={!title.trim() || isSubmitting}
                        onClick={() => void submit()}
                    >
                        Tạo
                    </button>
                </div>
            </div>
        </div>
    )
}
