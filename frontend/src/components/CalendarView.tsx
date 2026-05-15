import { useEffect, useMemo, useRef, useState } from 'react'
import { Calendar as BigCalendar } from 'react-big-calendar'
import { CheckCircle2, Clock3, MapPin, Tag, Trash2, X, Plus, RefreshCw, Repeat } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { clsx } from 'clsx'
import type { Schedule } from '../types'
import { localizer } from '../utils/calendar'

function parseServerDateTime(value: string): Date {
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    return parseISO(hasTimezone ? value : `${value}Z`)
}

function formatTimeRange(start: Date, end: Date): string {
    return `${format(start, 'HH:mm')} – ${format(end, 'HH:mm')}`
}

function toLocalInputDateTime(value: Date): string {
    const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 16)
}

// Round a date DOWN to the nearest 30-minute mark
function snapTo30(date: Date): Date {
    const snapped = new Date(date)
    const mins = snapped.getMinutes()
    snapped.setMinutes(mins < 30 ? 0 : 30, 0, 0)
    return snapped
}

type CalendarEvent = { title: string; start: Date; end: Date; resource: Schedule }

interface CalendarViewProps {
    schedules: Schedule[]
    isGoogleCalendarConnected?: boolean
    startDate: string
    endDate: string
    onStartDateChange: (date: string) => void
    onEndDateChange: (date: string) => void
    onFetch: () => void
    onOpenCreateEvent: () => void
    onSlotSelect?: (start: Date, end: Date) => void
    onToggleComplete: (item: Schedule) => Promise<void>
    onRemove: (id: string) => Promise<void>
}

const TYPE_LABELS: Record<string, string> = {
    CLASS: 'Class', DEADLINE: 'Deadline', EXAM: 'Exam', PERSONAL: 'Personal',
}


export function CalendarView({
    isGoogleCalendarConnected = false,
    schedules, startDate, endDate,
    onStartDateChange, onEndDateChange,
    onFetch, onOpenCreateEvent, onSlotSelect, onToggleComplete, onRemove,
}: CalendarViewProps) {
    const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null)
    const [currentDate, setCurrentDate] = useState<Date>(() => new Date(startDate))
    const [currentView, setCurrentView] = useState<'week' | 'day' | 'month'>('week')

    const onFetchRef = useRef(onFetch)
    useEffect(() => {
        onFetchRef.current = onFetch
    }, [onFetch])

    // Auto-fetch whenever the visible range changes
    useEffect(() => {
        onFetchRef.current()
    }, [startDate, endDate])

    const calendarEvents = useMemo<CalendarEvent[]>(
        () => schedules.map((item) => ({
            title: item.title,
            start: parseServerDateTime(item.start_time),
            end: parseServerDateTime(item.end_time),
            resource: item,
        })),
        [schedules],
    )

    const viewConfig = useMemo(() => {
        // Default visible window: 07:00 – 22:00
        // Expands automatically when events fall outside this range
        let windowStartMin = 7 * 60   // 07:00
        let windowEndMin = 22 * 60  // 22:00
        const now = new Date()
        const nowMin = now.getHours() * 60 + now.getMinutes()

        if (calendarEvents.length > 0) {
            const earliest = Math.min(
                ...calendarEvents.map((e) => e.start.getHours() * 60 + e.start.getMinutes())
            )
            const latest = Math.max(
                ...calendarEvents.map((e) => e.end.getHours() * 60 + e.end.getMinutes())
            )
            // Expand start: floor down to the hour (e.g. 6:30 → 6:00, 5:10 → 5:00)
            if (earliest < windowStartMin) {
                windowStartMin = Math.floor(earliest / 60) * 60
            }
            // Expand end: ceil up to next full hour (e.g. 22:30 → 23:00)
            if (latest > windowEndMin) {
                windowEndMin = Math.min(Math.ceil(latest / 60) * 60, 24 * 60)
            }
        }

        // react-big-calendar only shows the current-time indicator when now is inside [min, max].
        // Keep the visible window covering the current hour to avoid intermittent missing indicator.
        windowStartMin = Math.min(windowStartMin, Math.floor(nowMin / 60) * 60)
        windowEndMin = Math.max(windowEndMin, Math.min(Math.ceil((nowMin + 1) / 60) * 60, 24 * 60))

        const toClockDate = (totalMinutes: number, isEnd = false): Date => {
            const bounded = Math.max(0, Math.min(totalMinutes, 24 * 60))
            if (isEnd && bounded >= 24 * 60) {
                return new Date(1970, 0, 1, 23, 59, 59, 999)
            }
            const hours = Math.floor(bounded / 60)
            const minutes = bounded % 60
            return new Date(1970, 0, 1, Math.min(hours, 23), minutes)
        }

        return {
            min: toClockDate(windowStartMin),
            max: toClockDate(windowEndMin, true),
            // 30-min slots for precise click-to-create, 2 per hour group
            // Label gutter shows only whole hours (CSS hides the :30 label)
            step: 30,
            timeslots: 2,
        }
    }, [calendarEvents])

    const syncRangeToFilters = (rangeStart: Date, rangeEnd: Date) => {
        onStartDateChange(toLocalInputDateTime(rangeStart))
        onEndDateChange(toLocalInputDateTime(rangeEnd))
    }

    // Compute date range for a given view + anchor — view passed explicitly
    // so it's never stale when called right after setCurrentView()
    const computeRange = (forView: 'week' | 'day' | 'month', anchor: Date) => {
        const start = new Date(anchor)
        const end = new Date(anchor)
        if (forView === 'month') {
            start.setDate(1); start.setHours(0, 0, 0, 0)
            end.setMonth(end.getMonth() + 1, 0); end.setHours(23, 59, 59, 999)
        } else if (forView === 'day') {
            start.setHours(0, 0, 0, 0); end.setHours(23, 59, 59, 999)
        } else {
            // week — Mon-based
            const day = anchor.getDay()
            const diff = day === 0 ? -6 : 1 - day
            start.setDate(anchor.getDate() + diff); start.setHours(0, 0, 0, 0)
            end.setDate(start.getDate() + 6); end.setHours(23, 59, 59, 999)
        }
        return { start, end }
    }

    const handleNavigate = (nextDate: Date) => {
        setCurrentDate(nextDate)
        const { start, end } = computeRange(currentView, nextDate)
        syncRangeToFilters(start, end)
    }

    const handleViewChange = (v: string) => {
        const nextView = v as 'week' | 'day' | 'month'
        // When switching to day view, anchor to today — not to the week's Monday
        const anchor = nextView === 'day' ? new Date() : currentDate
        setCurrentView(nextView)
        setCurrentDate(anchor)
        const { start, end } = computeRange(nextView, anchor)
        syncRangeToFilters(start, end)
    }

    const handleSelectSlot = ({ start, end }: { start: Date; end: Date }) => {
        if (onSlotSelect) {
            // Snap start to the nearest 15-min mark for precision
            const snappedStart = snapTo30(start)
            const endTime = new Date(end)
            // Ensure at least 1h duration
            if (endTime.getTime() - snappedStart.getTime() < 60 * 60 * 1000) {
                endTime.setTime(snappedStart.getTime() + 60 * 60 * 1000)
            }
            onSlotSelect(snappedStart, endTime)
        } else {
            onOpenCreateEvent()
        }
    }

    const selectedStart = selectedSchedule ? parseServerDateTime(selectedSchedule.start_time) : null
    const selectedEnd = selectedSchedule ? parseServerDateTime(selectedSchedule.end_time) : null

    return (
        <div className="calendar-panel">
            {/* Header */}
            <div className="calendar-header">
                <div className="calendar-title-wrap">
                    <h1 className="page-title">Schedule</h1>
                    {isGoogleCalendarConnected && (
                        <div className="google-calendar-connected">
                            <img src="https://ssl.gstatic.com/calendar/images/dynamiclogo_2020q4/calendar_8_2x.png" alt="Google Calendar" />
                        </div>
                    )}
                </div>
                <div className="calendar-header-right">
                    <button type="button" className="topbar-btn" onClick={onFetch}>
                        <RefreshCw size={13} />
                    </button>
                    <button type="button" className="topbar-btn primary" onClick={onOpenCreateEvent}>
                        <Plus size={14} /> New event
                    </button>
                </div>
            </div>

            {/* Calendar */}
            <div className="calendar-container">
                <BigCalendar
                    localizer={localizer}
                    events={calendarEvents}
                    startAccessor="start"
                    endAccessor="end"
                    date={currentDate}
                    view={currentView}
                    views={['week', 'day', 'month']}
                    selectable
                    onNavigate={handleNavigate}
                    onView={handleViewChange}
                    onSelectEvent={(event) => setSelectedSchedule((event as CalendarEvent).resource)}
                    onSelectSlot={handleSelectSlot}
                    // step=30 → 30-min slots like Google Calendar, timeslots=2 → 2 per hour group
                    step={viewConfig.step}
                    timeslots={viewConfig.timeslots}
                    min={viewConfig.min}
                    max={viewConfig.max}
                    allDayAccessor={() => false}
                    showMultiDayTimes
                    components={{
                        event: ({ event }) => {
                            const item = event.resource as Schedule
                            const start = (event as CalendarEvent).start
                            const end = (event as CalendarEvent).end
                            return (
                                <div
                                    className={clsx('cal-event', `cal-event-${item.type}`, item.is_completed && 'is-completed')}
                                    title={`${item.title}${item.location ? ` • ${item.location}` : ''} • ${formatTimeRange(start, end)}`}
                                >
                                    <div className="cal-event-title">
                                        {item.title}
                                        {item.recurrence && item.recurrence.freq !== 'NONE' && (
                                            <Repeat size={12} style={{ marginLeft: 4, opacity: 0.7 }} />
                                        )}
                                    </div>
                                    <div className="cal-event-time">{formatTimeRange(start, end)}</div>
                                </div>
                            )
                        },
                    }}
                    formats={{
                        timeGutterFormat: 'HH:mm',
                    }}
                />
            </div>

            {/* Event Detail Modal */}
            {selectedSchedule && selectedStart && selectedEnd && (
                <div className="modal-backdrop" onClick={() => setSelectedSchedule(null)}>
                    <div className="modal" onClick={(e) => e.stopPropagation()}>
                        <div className="modal-header">
                            <div className="modal-title-area">
                                <div className={`modal-event-type-badge badge-${selectedSchedule.type}`}>
                                    {TYPE_LABELS[selectedSchedule.type] ?? selectedSchedule.type}
                                </div>
                                <div className="modal-title">{selectedSchedule.title}</div>
                            </div>
                            <button type="button" className="modal-close" onClick={() => setSelectedSchedule(null)}>
                                <X size={15} />
                            </button>
                        </div>

                        <div className="modal-body">
                            <div className="modal-meta-list">
                                <div className="modal-meta-row">
                                    <Clock3 size={14} className="modal-meta-icon" />
                                    <span className="modal-meta-text">
                                        {format(selectedStart, 'EEEE, MMM d, yyyy')} · {formatTimeRange(selectedStart, selectedEnd)}
                                    </span>
                                </div>
                                
                                {/* Recurrence indicator */}
                                {selectedSchedule.recurrence && selectedSchedule.recurrence.freq !== 'NONE' && (
                                    <div className="modal-meta-row">
                                        <Repeat size={14} className="modal-meta-icon" />
                                        <span className="modal-meta-text">
                                            {selectedSchedule.recurrence.freq === 'DAILY' && 'Daily'}
                                            {selectedSchedule.recurrence.freq === 'WEEKLY' && 'Weekly'}
                                            {selectedSchedule.recurrence.freq === 'MONTHLY' && 'Monthly'}
                                            {selectedSchedule.recurrence.interval && selectedSchedule.recurrence.interval > 1 && ` every ${selectedSchedule.recurrence.interval}`}
                                        </span>
                                    </div>
                                )}
                                
                                {selectedSchedule.location && (
                                    <div className="modal-meta-row">
                                        <MapPin size={14} className="modal-meta-icon" />
                                        <span className="modal-meta-text">{selectedSchedule.location}</span>
                                    </div>
                                )}
                                <div className="modal-meta-row">
                                    <Tag size={14} className="modal-meta-icon" />
                                    <span className="modal-meta-text" style={{ color: 'var(--text-tertiary)' }}>
                                        {selectedSchedule.is_completed ? 'Completed' : 'In progress'}
                                    </span>
                                </div>
                            </div>

                            {selectedSchedule.description && (
                                <div className="modal-description">
                                    <div className="modal-description-label">Notes</div>
                                    <p>{selectedSchedule.description}</p>
                                </div>
                            )}
                        </div>

                        <div className="modal-footer">
                            <button
                                type="button"
                                className="btn btn-danger"
                                onClick={async () => { if (selectedSchedule.id) { await onRemove(selectedSchedule.id); } setSelectedSchedule(null) }}
                            >
                                <Trash2 size={13} /> Delete
                            </button>
                            <div className="modal-footer-right">
                                <button type="button" className="btn btn-ghost" onClick={() => setSelectedSchedule(null)}>
                                    Close
                                </button>
                                <button
                                    type="button"
                                    className="btn btn-primary"
                                    onClick={async () => { await onToggleComplete(selectedSchedule); setSelectedSchedule(null) }}
                                >
                                    <CheckCircle2 size={13} />
                                    {selectedSchedule.is_completed ? 'Mark in progress' : 'Mark complete'}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}