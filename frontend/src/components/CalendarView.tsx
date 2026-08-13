import { useEffect, useMemo, useRef, useState } from 'react'
import { Calendar as BigCalendar } from 'react-big-calendar'
import { Plus, RefreshCw, Repeat } from 'lucide-react'
import { format, startOfWeek, endOfWeek } from 'date-fns'
import { clsx } from 'clsx'
import type { CalendarItem, Schedule } from '../types'
import { localizer } from '../utils/calendar'
import {
    isMarker,
    isMarkerDone,
    toCalendarEntries,
    type CalendarEntry,
} from '../utils/calendarItems'
import { EventDetailModal } from './EventDetailModal'

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

interface CalendarViewProps {
    /**
     * The unified feed (2.6 M1): schedules and tasks in one shape. The grid
     * is drawn entirely from this — nothing here knows there are two tables,
     * it just obeys each item's `render_as`.
     */
    items: CalendarItem[]
    /**
     * Full schedule records, used only to open the detail modal on click.
     * The calendar item shape deliberately carries just what's needed to
     * *draw* an entry; editing an event still goes through the event
     * resource.
     */
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
    onUpdate?: (item: Schedule, patch: Partial<Schedule>) => Promise<boolean>
    onRemove: (id: string) => Promise<void>
}

export function CalendarView({
    isGoogleCalendarConnected = false,
    items, schedules, startDate, endDate,
    onStartDateChange, onEndDateChange,
    onFetch, onOpenCreateEvent, onSlotSelect, onToggleComplete, onUpdate, onRemove,
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

    // Split on `render_as`, which the server sends — never re-derived from
    // `kind` here. See utils/calendarItems.ts.
    const calendarEntries = useMemo<CalendarEntry[]>(() => toCalendarEntries(items), [items])

    // Only blocks size the visible hour window. Markers are excluded on
    // purpose: a task due at midnight must not drag the grid open to 00:00.
    const timedEntries = useMemo(
        () => calendarEntries.filter((entry) => !isMarker(entry)),
        [calendarEntries],
    )

    const viewConfig = useMemo(() => {
        // Default visible window: 07:00 – 22:00
        // Expands automatically when events fall outside this range
        let windowStartMin = 7 * 60   // 07:00
        let windowEndMin = 22 * 60  // 22:00
        const now = new Date()
        const nowMin = now.getHours() * 60 + now.getMinutes()

        if (timedEntries.length > 0) {
            const earliest = Math.min(
                ...timedEntries.map((e) => e.start.getHours() * 60 + e.start.getMinutes())
            )
            const latest = Math.max(
                ...timedEntries.map((e) => e.end.getHours() * 60 + e.end.getMinutes())
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
    }, [timedEntries])

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
            // week — Sunday-based, matching `localizer` (date-fns + enUS,
            // whose default weekStartsOn is 0/Sunday — the same convention
            // react-big-calendar actually draws, per the "Sun" column it
            // always shows first). This used to be hand-rolled as Monday-
            // based, which only agreed with what was on screen when the
            // anchor itself was a Monday — any other anchor (in particular
            // Sunday, e.g. right after switching from Day view, which
            // anchors to `new Date()`) fetched the *previous* week while
            // still labeling it as the current one, silently swapping in
            // wrong data.
            const weekStart = startOfWeek(anchor, { weekStartsOn: 0 })
            const weekEnd = endOfWeek(anchor, { weekStartsOn: 0 })
            start.setTime(weekStart.getTime())
            end.setTime(weekEnd.getTime())
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
                    events={calendarEntries}
                    startAccessor="start"
                    endAccessor="end"
                    date={currentDate}
                    view={currentView}
                    views={['week', 'day', 'month']}
                    selectable
                    onNavigate={handleNavigate}
                    onView={handleViewChange}
                    onSelectEvent={(event) => {
                        const entry = event as CalendarEntry
                        // Markers are tasks — there's no event to open. The
                        // task's own affordances live in the checklist and
                        // the "Hôm nay" screen (2.7).
                        if (isMarker(entry)) return
                        const full = schedules.find((s) => s.id === entry.id)
                        if (full) setSelectedSchedule(full)
                    }}
                    onSelectSlot={handleSelectSlot}
                    // step=30 → 30-min slots like Google Calendar, timeslots=2 → 2 per hour group
                    step={viewConfig.step}
                    timeslots={viewConfig.timeslots}
                    min={viewConfig.min}
                    max={viewConfig.max}
                    // Markers ride the all-day strip: present on the day,
                    // consuming none of the hour grid. This is the rendering
                    // half of "a task consumes time, it doesn't occupy it" —
                    // the data half is that no task row exists in `schedules`.
                    allDayAccessor={(event) => (event as CalendarEntry).allDay}
                    showMultiDayTimes
                    components={{
                        event: ({ event }) => {
                            const entry = event as CalendarEntry

                            // Task → milestone marker. No time range shown,
                            // because it doesn't have one: it's due *by*
                            // this day, it doesn't run *during* it.
                            if (isMarker(entry)) {
                                return (
                                    <div
                                        className={clsx('cal-task-marker', isMarkerDone(entry) && 'is-done')}
                                        title={`${entry.title} — due today`}
                                    >
                                        <span className="cal-task-marker-glyph" aria-hidden>◆</span>
                                        <span className="cal-task-marker-title">{entry.title}</span>
                                    </div>
                                )
                            }

                            // Schedule → time block, as before.
                            const full = schedules.find((s) => s.id === entry.id)
                            const typeClass = full ? `cal-event-${full.type}` : 'cal-event-PERSONAL'
                            return (
                                <div
                                    className={clsx('cal-event', typeClass, entry.status === 'completed' && 'is-completed')}
                                    title={`${entry.title}${entry.location ? ` • ${entry.location}` : ''} • ${formatTimeRange(entry.start, entry.end)}`}
                                >
                                    <div className="cal-event-title">
                                        {entry.title}
                                        {full?.recurrence && full.recurrence.freq !== 'NONE' && (
                                            <Repeat size={12} style={{ marginLeft: 4, opacity: 0.7 }} />
                                        )}
                                    </div>
                                    <div className="cal-event-time">{formatTimeRange(entry.start, entry.end)}</div>
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
            {selectedSchedule && (
                <EventDetailModal
                    schedule={selectedSchedule}
                    canEdit={Boolean(selectedSchedule.id) && Boolean(onUpdate)}
                    onUpdate={onUpdate ?? (async () => false)}
                    onToggleComplete={onToggleComplete}
                    onRemove={onRemove}
                    onClose={() => setSelectedSchedule(null)}
                />
            )}
        </div>
    )
}