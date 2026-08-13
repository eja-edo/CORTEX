import {
    addDays,
    addMonths,
    addWeeks,
    eachDayOfInterval,
    endOfMonth,
    endOfWeek,
    format,
    isSameDay,
    isSameMonth,
    parse,
    startOfMonth,
    startOfWeek,
    subMonths,
} from 'date-fns'

/** Monday-start weeks, matching this app's existing calendar convention. */
const WEEK_STARTS_ON = 1 as const

const WEEKDAY_LABELS_BY_GETDAY = [
    'Chủ nhật', 'Thứ 2', 'Thứ 3', 'Thứ 4', 'Thứ 5', 'Thứ 6', 'Thứ 7',
]

type DueDated = { due_date: string | null }
type Statused = { status: string }
type Prioritized = { priority: string | null }
type CompletedDated = { status: string; completed_at: string | null }

/**
 * Higher wins ties among tasks with the same due-date standing. Unset
 * (`null`) ranks below every explicit value — it is not the same as `low`.
 * Mirrors the backend's `_PRIORITY_WEIGHT` (`today.py`) so a due-date tie
 * resolves the same way wherever a task list gets ordered.
 */
const PRIORITY_WEIGHT: Record<string, number> = {
    urgent: 3,
    high: 2,
    medium: 1,
    low: 0,
}

export function taskPriorityWeight(priority: string | null): number {
    return priority ? (PRIORITY_WEIGHT[priority] ?? -1) : -1
}

/**
 * Due date first (soonest/most overdue first, undated last), priority as
 * the tiebreak when two tasks share a due date (or both have none). Zero
 * means "tied on both" — callers still want a further tiebreak, e.g.
 * `created_at`.
 */
export function compareByDueDateThenPriority<T extends DueDated & Prioritized>(a: T, b: T): number {
    if (a.due_date && b.due_date) {
        const byDate = a.due_date.localeCompare(b.due_date)
        if (byDate !== 0) return byDate
        return taskPriorityWeight(b.priority) - taskPriorityWeight(a.priority)
    }
    if (a.due_date) return -1
    if (b.due_date) return 1
    return taskPriorityWeight(b.priority) - taskPriorityWeight(a.priority)
}

/**
 * "Still around, not closed" — pending confirmation, actionable, or just
 * finished. Excludes `cancelled`/`rejected`, which move to the Tasks
 * dashboard's separate "Đã đóng" panel rather than any live list.
 *
 * The one status set both "Hôm nay" surfaces (the Home widget and the Tasks
 * dashboard's day view) filter by — previously each screen wrote its own
 * copy of this list (the Home widget's left out `pending_confirm`/`done`
 * entirely, and separately excluded event-linked tasks), which is exactly
 * why the two could show a different set of tasks for what is nominally the
 * same "hôm nay". Sharing the constant makes that class of drift a compile
 * error (add a status here once) instead of two lists to keep in sync by
 * hand.
 */
export const LIVE_TASK_STATUSES = new Set(['pending_confirm', 'todo', 'in_progress', 'done'])

export function isLiveTask(task: Statused): boolean {
    return LIVE_TASK_STATUSES.has(task.status)
}

/**
 * Whether a `done` task still belongs in "today": only for the day it was
 * actually finished. Without this a task ticked off yesterday (due date
 * unset, or already in the past) would satisfy `isDueTodayOrEarlierOrUndated`
 * forever and never leave the list — nothing else ages it out. A task that
 * isn't `done` falls through to the plain due-date check.
 */
export function isVisibleToday<T extends DueDated & CompletedDated>(task: T, today = todayIso()): boolean {
    if (task.status === 'done') {
        return !!task.completed_at && localDateOfUtcTimestamp(task.completed_at) === today
    }
    return isDueTodayOrEarlierOrUndated(task, today)
}

/**
 * The exact set either "Hôm nay" surface shows: live-status tasks that are
 * overdue, due today, undated, or (for `done`) finished today. Both the Home
 * widget (`useTodayChecklist`) and the Tasks dashboard's day view build
 * their "today" list from this one function so the two can't disagree about
 * what belongs in it.
 */
export function selectTodayTasks<T extends DueDated & Statused & CompletedDated>(tasks: T[], today = todayIso()): T[] {
    return tasks.filter((task) => isLiveTask(task) && isVisibleToday(task, today))
}

export function todayIso(): string {
    return format(new Date(), 'yyyy-MM-dd')
}

export function toIso(date: Date): string {
    return format(date, 'yyyy-MM-dd')
}

export function fromIso(iso: string): Date {
    return parse(iso, 'yyyy-MM-dd', new Date())
}

/**
 * The `yyyy-MM-dd` prefix of a task's `due_date` — which is usually already
 * just that, but can carry a real time now (e.g. an event checklist item
 * inherits the event's `end_time`). Bucketing/grouping below is by day only,
 * same as before; this is the one place that assumption is made explicit.
 */
export function dateOnly(dueDate: string): string {
    return dueDate.slice(0, 10)
}

/**
 * The local calendar day a UTC instant field (`completed_at`, `updated_at`
 * — a real moment in time, unlike `due_date`'s bare wall-clock string) falls
 * on in this browser's timezone. `dateOnly` must NOT be used for these: the
 * backend serializes its naive-UTC `datetime` columns with no `Z`/offset at
 * all (see `models._utcnow` / `TaskService`), so slicing the raw string
 * reads off the *UTC* day, not the user's — for anyone east of UTC that's
 * flat-out wrong near midnight (23:50 local can already be tomorrow in UTC,
 * or vice versa west of UTC), and for everyone else it silently depends on
 * the server's clock instead of the browser's. This appends `Z` before
 * parsing so `Date` treats the string as the UTC instant it actually is,
 * then reads the day back out in local time.
 */
export function localDateOfUtcTimestamp(utcTimestamp: string): string {
    const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(utcTimestamp)
    return toIso(new Date(hasZone ? utcTimestamp : `${utcTimestamp}Z`))
}

/** "Oct 8" — the compact form checklist rows show instead of the raw
 * `yyyy-MM-dd`. Takes the already-extracted day (`dateOnly`), not a full
 * `due_date`, so it stays agnostic of whether a time is attached. */
export function formatCompactDate(isoDate: string): string {
    return format(fromIso(isoDate), 'MMM d')
}

/**
 * A `Date` as a naive local wall-clock string ("2026-08-10T15:00:00", no
 * offset) — for sending as `due_date`, which is stored without a timezone
 * (see `models.Task.due_date`): the user's own "done by 3pm my time" fact,
 * not a real-world instant. `format` (unlike `toISOString`) reads local
 * fields, so this needs no manual offset math.
 */
export function toLocalDateTimeIso(date: Date): string {
    return format(date, "yyyy-MM-dd'T'HH:mm:ss")
}

/** Move a `yyyy-MM-dd` string by whole days — for the day view's ‹ › arrows. */
export function shiftIsoDate(iso: string, days: number): string {
    return toIso(addDays(fromIso(iso), days))
}

/** Move a week reference forward/back by whole weeks — for the week view's
 * ‹ › arrows. Negative `weeks` goes back. */
export function shiftWeek(reference: Date, weeks: number): Date {
    return addWeeks(reference, weeks)
}

/** "dd/MM", for compact date labels (week range, day nav). */
export function formatShort(date: Date): string {
    return format(date, 'dd/MM')
}

export function weekdayLabel(date: Date): string {
    return WEEKDAY_LABELS_BY_GETDAY[date.getDay()]
}

/**
 * The "Hôm nay" bucket: overdue, due today, or with no due date at all.
 * Undated tasks live here rather than nowhere — they're the ones with no
 * home in the week/month grids, and hiding them would be losing them.
 */
export function isDueTodayOrEarlierOrUndated(task: DueDated, today = todayIso()): boolean {
    return !task.due_date || dateOnly(task.due_date) <= today
}

/** Strictly past its due date, and not finished — the one state a task
 * list needs to call out, since it's the one deadline that's already
 * broken rather than merely approaching. */
export function isTaskOverdue<T extends DueDated & Statused>(task: T, today = todayIso()): boolean {
    return task.status !== 'done' && !!task.due_date && dateOnly(task.due_date) < today
}

/** The 7 days (Mon–Sun) of the week containing `reference`. */
export function weekDays(reference: Date = new Date()): Date[] {
    return eachDayOfInterval({
        start: startOfWeek(reference, { weekStartsOn: WEEK_STARTS_ON }),
        end: endOfWeek(reference, { weekStartsOn: WEEK_STARTS_ON }),
    })
}

/** Every cell of a month's calendar grid, padded to full weeks so the grid
 * is always a rectangle (partial weeks at the start/end of the month
 * borrow days from the neighbouring month, shown dimmed by the caller). */
export function monthGridDays(reference: Date = new Date()): Date[] {
    const monthStart = startOfMonth(reference)
    const monthEnd = endOfMonth(reference)
    return eachDayOfInterval({
        start: startOfWeek(monthStart, { weekStartsOn: WEEK_STARTS_ON }),
        end: endOfWeek(monthEnd, { weekStartsOn: WEEK_STARTS_ON }),
    })
}

export function isInCurrentMonth(date: Date, reference: Date): boolean {
    return isSameMonth(date, reference)
}

export function isToday(date: Date): boolean {
    return isSameDay(date, new Date())
}

export function tasksDueOn<T extends DueDated>(tasks: T[], date: Date): T[] {
    const iso = toIso(date)
    return tasks.filter((t) => t.due_date != null && dateOnly(t.due_date) === iso)
}

export function nextMonth(reference: Date): Date {
    return addMonths(reference, 1)
}

export function previousMonth(reference: Date): Date {
    return subMonths(reference, 1)
}

export function monthLabel(reference: Date): string {
    return format(reference, 'MM/yyyy')
}
