import { useMemo, useState } from 'react'
import { Calendar as BigCalendar } from 'react-big-calendar'
import { CheckCircle2, Clock3, MapPin, Tag, Trash2, X, Plus, RefreshCw, } from 'lucide-react'
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
    onToggleComplete: (item: Schedule) => Promise<void>
    onRemove: (id: string) => Promise<void>
}

const TYPE_LABELS: Record<string, string> = {
    CLASS: 'Class', DEADLINE: 'Deadline', EXAM: 'Exam', PERSONAL: 'Personal',
}

export function CalendarView({
    isGoogleCalendarConnected = false,
    schedules, startDate,
    onStartDateChange, onEndDateChange,
    onFetch, onOpenCreateEvent, onToggleComplete, onRemove,
}: CalendarViewProps) {
    const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null)
    const [currentDate, setCurrentDate] = useState<Date>(() => new Date(startDate))
    const [currentView, setCurrentView] = useState<'week' | 'day' | 'month'>('week')

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
        if (calendarEvents.length === 0) {
            return { min: new Date(1970, 0, 1, 7, 0), max: new Date(1970, 0, 1, 22, 0), step: 60 }
        }
        const totalDuration = calendarEvents.reduce((sum, e) => sum + Math.max(15, Math.round((e.end.getTime() - e.start.getTime()) / 60000)), 0)
        const avg = totalDuration / calendarEvents.length
        const step = calendarEvents.length >= 16 || avg <= 45 ? 15 : calendarEvents.length >= 9 || avg <= 90 ? 30 : 60
        const earliest = Math.min(...calendarEvents.map((e) => e.start.getHours() * 60 + e.start.getMinutes()))
        const latest = Math.max(...calendarEvents.map((e) => e.end.getHours() * 60 + e.end.getMinutes()))
        const minMin = Math.max(0, earliest - 60)
        const maxMin = Math.min(24 * 60 - 1, latest + 60)
        return {
            min: new Date(1970, 0, 1, Math.floor(minMin / 60), minMin % 60),
            max: new Date(1970, 0, 1, Math.floor(maxMin / 60), maxMin % 60),
            step,
        }
    }, [calendarEvents])

    const syncRangeToFilters = (rangeStart: Date, rangeEnd: Date) => {
        onStartDateChange(toLocalInputDateTime(rangeStart))
        onEndDateChange(toLocalInputDateTime(rangeEnd))
    }

    const handleNavigate = (nextDate: Date) => {
        setCurrentDate(nextDate)
        const start = new Date(nextDate)
        const end = new Date(nextDate)
        if (currentView === 'month') {
            start.setDate(1); start.setHours(0, 0, 0, 0)
            end.setMonth(end.getMonth() + 1, 0); end.setHours(23, 59, 59, 999)
        } else if (currentView === 'day') {
            start.setHours(0, 0, 0, 0); end.setHours(23, 59, 59, 999)
        } else {
            const day = nextDate.getDay()
            const diff = day === 0 ? -6 : 1 - day
            start.setDate(nextDate.getDate() + diff); start.setHours(0, 0, 0, 0)
            end.setDate(start.getDate() + 6); end.setHours(23, 59, 59, 999)
        }
        syncRangeToFilters(start, end)
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
                    onNavigate={handleNavigate}
                    onView={(v) => { setCurrentView(v as 'week' | 'day' | 'month'); handleNavigate(currentDate) }}
                    onSelectEvent={(event) => setSelectedSchedule((event as CalendarEvent).resource)}
                    step={viewConfig.step}
                    timeslots={1}
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
                                    <div className="cal-event-title">{item.title}</div>
                                    <div className="cal-event-time">{formatTimeRange(start, end)}</div>
                                </div>
                            )
                        },
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
                                onClick={async () => { await onRemove(selectedSchedule.id); setSelectedSchedule(null) }}
                            >
                                <Trash2 size={13} /> Delete
                            </button>
                            <div className="modal-footer-right">
                                <button
                                    type="button"
                                    className="btn btn-ghost"
                                    onClick={() => setSelectedSchedule(null)}
                                >
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