import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { Check } from 'lucide-react'
import { clsx } from 'clsx'
import type { TaskPriority } from '../types'
import { PriorityIcon } from './PriorityIcon'
import { PRIORITY_LABELS } from '../utils/taskPriority'

const OPTIONS: (TaskPriority | null)[] = [null, 'urgent', 'high', 'medium', 'low']

/**
 * Compact priority picker — Linear's "change priority to…" list, not the
 * full due-date/priority/description form. Selecting an option applies it
 * immediately and closes; there's no separate save step.
 *
 * Portaled to `document.body` and positioned from `anchorRef`'s rect
 * (the same approach as `UserMenu`) rather than `position: absolute` inside
 * the row — a row this deep in a scrollable list gets its dropdown clipped
 * by the panel's `overflow: auto` otherwise.
 */
export function PriorityMenu({
    anchorRef,
    value,
    onSelect,
    onClose,
}: {
    anchorRef: RefObject<HTMLElement | null>
    value: TaskPriority | null
    onSelect: (priority: TaskPriority | null) => void
    onClose: () => void
}) {
    const menuRef = useRef<HTMLDivElement>(null)
    const [style, setStyle] = useState<React.CSSProperties>({ visibility: 'hidden' })

    const updatePosition = useCallback(() => {
        const anchor = anchorRef.current
        if (!anchor) return
        const rect = anchor.getBoundingClientRect()
        setStyle({
            position: 'fixed',
            top: `${rect.bottom + 4}px`,
            left: `${rect.left}px`,
        })
    }, [anchorRef])

    useEffect(() => {
        updatePosition()
        window.addEventListener('scroll', updatePosition, true)
        window.addEventListener('resize', updatePosition)
        return () => {
            window.removeEventListener('scroll', updatePosition, true)
            window.removeEventListener('resize', updatePosition)
        }
    }, [updatePosition])

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node
            if (anchorRef.current?.contains(target)) return
            if (menuRef.current?.contains(target)) return
            onClose()
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [anchorRef, onClose])

    return createPortal(
        <div ref={menuRef} className="priority-menu" role="menu" style={style}>
            {OPTIONS.map((opt) => (
                <button
                    key={opt ?? 'none'}
                    type="button"
                    role="menuitemradio"
                    aria-checked={value === opt}
                    className={clsx('priority-menu-item', opt && `is-${opt}`)}
                    onClick={() => onSelect(opt)}
                >
                    <PriorityIcon priority={opt} />
                    <span>{opt ? PRIORITY_LABELS[opt] : 'Không ưu tiên'}</span>
                    {value === opt && <Check size={13} className="priority-menu-check" />}
                </button>
            ))}
        </div>,
        document.body,
    )
}
