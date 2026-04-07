import { useMemo, useState } from 'react'
import { Calendar as CalendarIcon, CheckCircle2, Clock3, MapPin, Plus, RefreshCw, Tag, Trash2 } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import { Calendar as BigCalendar } from 'react-big-calendar'
import { clsx } from 'clsx'
import type { Schedule } from '../types'
import { localizer } from '../utils/calendar'

function parseServerDateTime(value: string): Date {
    // Backend currently returns naive datetimes (no timezone suffix).
    // Treat these values as UTC to keep calendar rendering consistent across client timezones.
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    return parseISO(hasTimezone ? value : `${value}Z`)
}

function formatTimeRange(start: Date, end: Date): string {
    return `${format(start, 'HH:mm')} - ${format(end, 'HH:mm')}`
}

function toLocalInputDateTime(value: Date): string {
    const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    return local.toISOString().slice(0, 16)
}

type CalendarEvent = {
    title: string
    start: Date
    end: Date
    resource: Schedule
}

interface CalendarViewProps {
    schedules: Schedule[]
    startDate: string
    endDate: string
    onStartDateChange: (date: string) => void
    onEndDateChange: (date: string) => void
    onFetch: () => void
    onOpenCreateEvent: () => void
    onToggleComplete: (item: Schedule) => Promise<void>
    onRemove: (id: string) => Promise<void>
}

export function CalendarView({
    schedules,
    startDate,
    endDate,
    onStartDateChange,
    onEndDateChange,
    onFetch,
    onOpenCreateEvent,
    onToggleComplete,
    onRemove,
}: CalendarViewProps) {
    const [selectedSchedule, setSelectedSchedule] = useState<Schedule | null>(null)
    const [currentDate, setCurrentDate] = useState<Date>(() => new Date(startDate))
    const [currentView, setCurrentView] = useState<'week' | 'day' | 'month'>('week')

    const calendarEvents = useMemo<CalendarEvent[]>(
        () =>
            schedules.map((item) => ({
                title: item.title,
                start: parseServerDateTime(item.start_time),
                end: parseServerDateTime(item.end_time),
                resource: item,
            })),
        [schedules],
    )

    const viewConfig = useMemo(() => {
        if (calendarEvents.length === 0) {
            const min = new Date(1970, 0, 1, 0, 0, 0, 0)
            const max = new Date(1970, 0, 1, 23, 59, 59, 999)
            return { min, max, step: 360 }
        }

        const totalDurationMinutes = calendarEvents.reduce((sum, event) => {
            const diff = Math.max(15, Math.round((event.end.getTime() - event.start.getTime()) / 60000))
            return sum + diff
        }, 0)
        const averageDuration = totalDurationMinutes / calendarEvents.length

        let step = 60
        if (calendarEvents.length >= 16 || averageDuration <= 45) {
            step = 15
        } else if (calendarEvents.length >= 9 || averageDuration <= 90) {
            step = 30
        }

        const earliestMinute = Math.min(...calendarEvents.map((event) => event.start.getHours() * 60 + event.start.getMinutes()))
        const latestMinute = Math.max(...calendarEvents.map((event) => event.end.getHours() * 60 + event.end.getMinutes()))

        const minMinute = Math.max(0, earliestMinute - 60)
        const maxMinute = Math.min(24 * 60 - 1, latestMinute + 60)

        const min = new Date(1970, 0, 1, Math.floor(minMinute / 60), minMinute % 60, 0, 0)
        const max = new Date(1970, 0, 1, Math.floor(maxMinute / 60), maxMinute % 60, 0, 0)

        return { min, max, step }
    }, [calendarEvents])

    const emptyCalendarFormats = useMemo(
        () => ({
            timeGutterFormat: (date: Date) => {
                const hour = date.getHours()
                if (hour === 0) {
                    return '0:00 AM'
                }
                if (hour === 6) {
                    return '6:00 AM'
                }
                if (hour === 12) {
                    return '12:00 PM'
                }
                if (hour === 18) {
                    return '6:00 PM'
                }
                return ''
            },
        }),
        [],
    )

    const syncRangeToFilters = (rangeStart: Date, rangeEnd: Date) => {
        onStartDateChange(toLocalInputDateTime(rangeStart))
        onEndDateChange(toLocalInputDateTime(rangeEnd))
    }

    const handleNavigate = (nextDate: Date) => {
        setCurrentDate(nextDate)

        const start = new Date(nextDate)
        const end = new Date(nextDate)

        if (currentView === 'month') {
            start.setDate(1)
            start.setHours(0, 0, 0, 0)
            end.setMonth(end.getMonth() + 1, 0)
            end.setHours(23, 59, 59, 999)
        } else if (currentView === 'day') {
            start.setHours(0, 0, 0, 0)
            end.setHours(23, 59, 59, 999)
        } else {
            const day = nextDate.getDay()
            const diffToMonday = day === 0 ? -6 : 1 - day
            start.setDate(nextDate.getDate() + diffToMonday)
            start.setHours(0, 0, 0, 0)
            end.setDate(start.getDate() + 6)
            end.setHours(23, 59, 59, 999)
        }

        syncRangeToFilters(start, end)
    }

    const handleViewChange = (nextView: 'week' | 'day' | 'month') => {
        setCurrentView(nextView)
        handleNavigate(currentDate)
    }

    return (
        <article className="panel wide">
            <div className="schedule-toolbar">
                <h2>
                    <CalendarIcon size={20} style={{ display: 'inline', verticalAlign: 'text-bottom', marginRight: '6px' }} /> Your Schedule
                </h2>
                <div className="range-controls">
                    <label style={{ flexDirection: 'row', alignItems: 'center' }}>
                        <span style={{ color: 'var(--soft)' }}>From</span>
                        <input type="datetime-local" value={startDate} onChange={(e) => onStartDateChange(e.target.value)} />
                    </label>
                    <label style={{ flexDirection: 'row', alignItems: 'center' }}>
                        <span style={{ color: 'var(--soft)' }}>To</span>
                        <input type="datetime-local" value={endDate} onChange={(e) => onEndDateChange(e.target.value)} />
                    </label>
                    <button className="ghost" type="button" onClick={onFetch}>
                        <RefreshCw size={16} /> Filter
                    </button>
                    <button className="primary" type="button" onClick={onOpenCreateEvent}>
                        <Plus size={16} /> Add Event
                    </button>
                </div>
            </div>
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
                    onView={(nextView) => handleViewChange(nextView as 'week' | 'day' | 'month')}
                    onSelectEvent={(event) => setSelectedSchedule((event as CalendarEvent).resource)}
                    step={viewConfig.step}
                    timeslots={1}
                    min={viewConfig.min}
                    max={viewConfig.max}
                    formats={calendarEvents.length === 0 ? emptyCalendarFormats : undefined}
                    allDayAccessor={() => false}
                    showMultiDayTimes
                    components={{
                        event: ({ event }) => {
                            const item = event.resource as Schedule
                            const start = (event as CalendarEvent).start
                            const end = (event as CalendarEvent).end
                            const durationMin = Math.max(1, Math.round((end.getTime() - start.getTime()) / 60000))
                            const isCompact = durationMin <= 45

                            return (
                                <div
                                    className={clsx(
                                        'custom-rbc-event',
                                        `type-${item.type}`,
                                        item.is_completed && 'is-completed',
                                        isCompact && 'is-compact',
                                    )}
                                    title={`${item.title}${item.location ? ` • ${item.location}` : ''} • ${formatTimeRange(start, end)}`}
                                >
                                    <div className="event-inner">
                                        <span className="event-title">{item.title}</span>
                                        <span className="event-time">{formatTimeRange(start, end)}</span>
                                        {item.location && !isCompact ? <span className="event-location">{item.location}</span> : null}
                                    </div>
                                </div>
                            )
                        },
                    }}
                />
            </div>

            {selectedSchedule ? (
                <div className="event-modal-backdrop" onClick={() => setSelectedSchedule(null)}>
                    <div className="event-modal" onClick={(e) => e.stopPropagation()}>
                        <div className="event-modal-header">
                            <h3>{selectedSchedule.title}</h3>
                            <button className="ghost" type="button" onClick={() => setSelectedSchedule(null)}>
                                Close
                            </button>
                        </div>

                        <div className="event-meta-grid">
                            <p>
                                <Tag size={14} />
                                <span>Type: {selectedSchedule.type}</span>
                            </p>
                            <p>
                                <Clock3 size={14} />
                                <span>
                                    {format(parseServerDateTime(selectedSchedule.start_time), 'dd/MM/yyyy HH:mm')} -{' '}
                                    {format(parseServerDateTime(selectedSchedule.end_time), 'dd/MM/yyyy HH:mm')}
                                </span>
                            </p>
                            {selectedSchedule.location ? (
                                <p>
                                    <MapPin size={14} />
                                    <span>{selectedSchedule.location}</span>
                                </p>
                            ) : null}
                            <p>
                                <CheckCircle2 size={14} />
                                <span>Status: {selectedSchedule.is_completed ? 'Completed' : 'In progress'}</span>
                            </p>
                        </div>

                        {selectedSchedule.description ? (
                            <div className="event-description">
                                <h4>Notes</h4>
                                <p>{selectedSchedule.description}</p>
                            </div>
                        ) : null}

                        <div className="event-modal-actions">
                            <button
                                className="ghost"
                                type="button"
                                onClick={async () => {
                                    await onToggleComplete(selectedSchedule)
                                    setSelectedSchedule(null)
                                }}
                            >
                                <CheckCircle2 size={16} />
                                {selectedSchedule.is_completed ? 'Mark In progress' : 'Mark Completed'}
                            </button>
                            <button
                                className="danger"
                                type="button"
                                onClick={async () => {
                                    await onRemove(selectedSchedule.id)
                                    setSelectedSchedule(null)
                                }}
                            >
                                <Trash2 size={16} /> Delete Event
                            </button>
                        </div>
                    </div>
                </div>
            ) : null}
        </article>
    )
}
