/**
 * Calendar item mapping (Milestone 2.6).
 *
 * The server sends schedules and tasks in one shape, each carrying
 * `render_as`. This module splits that feed for the calendar — and it splits
 * on `render_as`, never on `kind`.
 *
 * That distinction matters: re-deriving "tasks are markers" on the client
 * would put the rule in two places, and the day they disagree is the day a
 * task gets drawn as a time block. The server owns the mapping; this file
 * just obeys it.
 */

import type { CalendarItem } from '../types'

/** A schedule: occupies a span in the time grid. */
export type CalendarBlock = {
    id: string
    title: string
    start: Date
    end: Date
    status: string
    location: string | null
    allDay: false
    item: CalendarItem
}

/**
 * A task: a point in the day.
 *
 * `allDay: true` keeps it out of the hour grid entirely — react-big-calendar
 * renders these in the strip above the timed area. That is the rendering
 * equivalent of the data rule: a task has a deadline, it does not book time,
 * so it must never consume a slot that would make the user look busy.
 */
export type CalendarMarker = {
    id: string
    title: string
    start: Date
    end: Date
    status: string
    allDay: true
    item: CalendarItem
}

export type CalendarEntry = CalendarBlock | CalendarMarker

/** Server datetimes are naive UTC unless they say otherwise. */
export function parseServerDateTime(value: string): Date {
    const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
    return new Date(hasTimezone ? value : `${value}Z`)
}

/**
 * Read the calendar day out of a server datetime and build a local midnight
 * from it. No timezone maths: the day is the day.
 */
export function parseServerDay(value: string): Date {
    const [year, month, day] = value.slice(0, 10).split('-').map(Number)
    return new Date(year, month - 1, day)
}

export function isBlock(entry: CalendarEntry): entry is CalendarBlock {
    return entry.allDay === false
}

export function isMarker(entry: CalendarEntry): entry is CalendarMarker {
    return entry.allDay === true
}

/**
 * Turn one server item into something the calendar can draw.
 *
 * Returns null for an item that can't be placed — a `block` with no times or
 * a `marker` with no due date. Dropping it is deliberate: guessing a
 * position would put a fake commitment on the user's day.
 */
export function toCalendarEntry(item: CalendarItem): CalendarEntry | null {
    if (item.render_as === 'block') {
        if (!item.start_time || !item.end_time) return null
        return {
            id: item.id,
            title: item.title,
            start: parseServerDateTime(item.start_time),
            end: parseServerDateTime(item.end_time),
            status: item.status,
            location: item.location,
            allDay: false,
            item,
        }
    }

    if (!item.due_date) return null
    // A due date is a calendar day, not an instant, so it is read as local
    // Y-M-D rather than parsed as UTC. Treating it as an instant would push
    // the marker onto the previous day for anyone west of UTC.
    const due = parseServerDay(item.due_date)
    return {
        id: item.id,
        title: item.title,
        // Start and end are the same instant: a marker has no duration, and
        // giving it one would make it look like booked time.
        start: due,
        end: due,
        status: item.status,
        allDay: true,
        item,
    }
}

export function toCalendarEntries(items: CalendarItem[]): CalendarEntry[] {
    return items
        .map(toCalendarEntry)
        .filter((entry): entry is CalendarEntry => entry !== null)
}

/** Tasks are done or not; anything else on a marker reads as still open. */
export function isMarkerDone(marker: CalendarMarker): boolean {
    return marker.status === 'done'
}
