import { describe, expect, it } from 'vitest'
import type { CalendarItem } from '../../types'
import {
    isBlock,
    isMarker,
    isMarkerDone,
    parseServerDay,
    toCalendarEntries,
    toCalendarEntry,
} from '../calendarItems'

function scheduleItem(overrides: Partial<CalendarItem> = {}): CalendarItem {
    return {
        id: 'sched-1',
        kind: 'schedule',
        render_as: 'block',
        title: 'Team sync',
        start_time: '2026-10-14T14:00:00+00:00',
        end_time: '2026-10-14T15:00:00+00:00',
        due_date: null,
        status: 'scheduled',
        location: 'Room 3',
        ...overrides,
    }
}

function taskItem(overrides: Partial<CalendarItem> = {}): CalendarItem {
    return {
        id: 'task-1',
        kind: 'task',
        render_as: 'marker',
        title: 'Write the API spec',
        start_time: null,
        end_time: null,
        due_date: '2026-10-14T00:00:00',
        status: 'todo',
        location: null,
        ...overrides,
    }
}

describe('calendar entry mapping', () => {
    it('draws a schedule as a timed block', () => {
        const entry = toCalendarEntry(scheduleItem())!
        expect(isBlock(entry)).toBe(true)
        expect(entry.allDay).toBe(false)
        expect(entry.start.getTime()).toBeLessThan(entry.end.getTime())
    })

    it('draws a task as an all-day marker so it never consumes a slot', () => {
        // This is the rendering half of "a task consumes time, it doesn't
        // occupy it". A marker in the hour grid would make the user look
        // busy, which is what 3.3 and 6.2 must never see.
        const entry = toCalendarEntry(taskItem())!
        expect(isMarker(entry)).toBe(true)
        expect(entry.allDay).toBe(true)
        expect(entry.start.getTime()).toBe(entry.end.getTime())
    })

    it('obeys render_as rather than re-deriving it from kind', () => {
        // If the server ever says a task should be drawn as a block, the
        // client follows. The mapping lives in one place — the server — so
        // the two can't drift.
        const entry = toCalendarEntry(
            taskItem({ render_as: 'block', start_time: '2026-10-14T09:00:00', end_time: '2026-10-14T10:00:00' }),
        )!
        expect(isBlock(entry)).toBe(true)
    })

    it('places a marker on its calendar day regardless of the viewer timezone', () => {
        // A due date is a day, not an instant. Parsing it as UTC would push
        // the marker to the previous day for anyone west of UTC.
        const due = parseServerDay('2026-10-14T00:00:00')
        expect(due.getFullYear()).toBe(2026)
        expect(due.getMonth()).toBe(9) // October
        expect(due.getDate()).toBe(14)
        expect(due.getHours()).toBe(0)
    })

    it('drops entries it cannot place instead of guessing', () => {
        expect(toCalendarEntry(scheduleItem({ start_time: null }))).toBeNull()
        expect(toCalendarEntry(taskItem({ due_date: null }))).toBeNull()
    })

    it('keeps both kinds in one list', () => {
        const entries = toCalendarEntries([scheduleItem(), taskItem()])
        expect(entries).toHaveLength(2)
        expect(entries.filter(isBlock)).toHaveLength(1)
        expect(entries.filter(isMarker)).toHaveLength(1)
    })

    it('filters unplaceable entries out of the list', () => {
        const entries = toCalendarEntries([
            scheduleItem(),
            taskItem({ due_date: null }),
        ])
        expect(entries).toHaveLength(1)
    })

    it('marks only done tasks as done', () => {
        const done = toCalendarEntry(taskItem({ status: 'done' }))!
        const open = toCalendarEntry(taskItem({ status: 'in_progress' }))!
        expect(isMarkerDone(done as never)).toBe(true)
        expect(isMarkerDone(open as never)).toBe(false)
    })
})
