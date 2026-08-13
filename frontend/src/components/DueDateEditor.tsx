import { useState } from 'react'
import { Clock, X } from 'lucide-react'
import { dateOnly } from '../utils/taskDateBuckets'

/**
 * A day and time carry no meaning: midnight is what every date-only task
 * already has, so it never counts as "a time was set" here.
 */
export function timePartOf(dueDate: string | null): string {
    if (!dueDate) return ''
    const match = dueDate.match(/T(\d{2}:\d{2})/)
    return match && match[1] !== '00:00' ? match[1] : ''
}

/**
 * A due date is a bare day by default (2.5) — this keeps that the common
 * case: one `<input type="date">`, same as before. A real time is opt-in via
 * the small clock toggle, for the rarer case a task genuinely needs one
 * (or already has one, e.g. inherited from an event's `end_time` — see
 * `useEventChecklist`), rather than asking every task creation to consider
 * an hour:minute it usually doesn't need.
 */
export function DueDateEditor({
    value,
    onChange,
    autoFocus = false,
    dateClassName,
    timeClassName,
    toggleClassName,
}: {
    value: string | null
    onChange: (next: string | null) => void
    autoFocus?: boolean
    dateClassName?: string
    timeClassName?: string
    toggleClassName?: string
}) {
    const [showTime, setShowTime] = useState(() => timePartOf(value) !== '')

    const date = value ? dateOnly(value) : ''
    const time = timePartOf(value)

    const setDate = (nextDate: string) => {
        if (!nextDate) {
            onChange(null)
            return
        }
        onChange(showTime && time ? `${nextDate}T${time}:00` : nextDate)
    }

    const setTime = (nextTime: string) => {
        if (!date) return
        onChange(nextTime ? `${date}T${nextTime}:00` : date)
    }

    return (
        <span className="due-date-editor">
            <input
                type="date"
                autoFocus={autoFocus}
                className={dateClassName}
                value={date}
                aria-label="Ngày hạn"
                onChange={(e) => setDate(e.target.value)}
            />
            {showTime ? (
                <>
                    <input
                        type="time"
                        className={timeClassName}
                        value={time}
                        aria-label="Giờ hạn"
                        onChange={(e) => setTime(e.target.value)}
                        onBlur={() => {
                            if (!time) setShowTime(false)
                        }}
                    />
                    <button
                        type="button"
                        className={toggleClassName}
                        title="Bỏ giờ"
                        aria-label="Bỏ giờ"
                        onClick={() => {
                            setShowTime(false)
                            if (date) onChange(date)
                        }}
                    >
                        <X size={10} />
                    </button>
                </>
            ) : (
                date && (
                    <button
                        type="button"
                        className={toggleClassName}
                        title="Thêm giờ"
                        aria-label="Thêm giờ"
                        onClick={() => setShowTime(true)}
                    >
                        <Clock size={11} />
                    </button>
                )
            )}
        </span>
    )
}
