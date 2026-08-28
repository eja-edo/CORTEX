import { useEffect, useMemo, useState } from 'react'
import { clsx } from 'clsx'
import {
    Check,
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    Plus,
    RotateCcw,
    Trash2,
    X,
} from 'lucide-react'
import { useTasksPage, type TaskWire } from '../hooks/useTasksPage'
import { useConfirmDialog } from '../hooks/useConfirmDialog'
import { useToast } from '../hooks/useToast'
import { TaskChecklistRow } from './TaskChecklistRow'
import { useProjectStore } from '../stores/projectStore'
import { SubtaskCreatePanel } from './SubtaskCreatePanel'
import type { TaskDetailPatch } from './TaskDetailPopover'
import { toggleTaskWithCascade } from '../utils/taskCascade'
import {
    dateOnly,
    formatShort,
    fromIso,
    isInCurrentMonth,
    isLiveTask,
    isVisibleToday,
    localDateOfUtcTimestamp,
    isToday as isTodayDate,
    monthGridDays,
    nextMonth,
    previousMonth,
    shiftIsoDate,
    shiftWeek,
    tasksDueOn,
    toIso,
    todayIso,
    weekDays,
    weekdayLabel,
} from '../utils/taskDateBuckets'
import { flattenTaskTree } from '../utils/taskTree'

const CLOSED_STATUS_LABELS: Record<'cancelled' | 'rejected', string> = {
    cancelled: 'Đã huỷ',
    rejected: 'Đã từ chối',
}

type TaskViewMode = 'day' | 'week' | 'month'

function formatDate(iso: string | null): string | null {
    if (!iso) return null
    return new Date(iso).toLocaleDateString('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
}

type TaskActions = {
    busyTaskId: string | null
    onConfirm: (task: TaskWire) => void
    onReject: (task: TaskWire) => void
    onToggle: (task: TaskWire) => void
    onRename: (id: string, title: string) => Promise<void>
    onSetDueDate: (id: string, date: string | null) => Promise<void>
    onUpdateDetail: (id: string, patch: TaskDetailPatch) => Promise<void>
    onRemove: (task: TaskWire) => void
    /** The detail modal can create/edit its own sub-tasks — a full refetch
     * on close is what makes those show up here without a page reload. */
    onDetailClose: () => void
}

/**
 * Tasks dashboard — every task, not just the handful "Hôm nay" ranks as
 * actionable right now.
 *
 * Organised by **when**, not by status: Hôm nay / Tuần này / Tháng này, each
 * with its own ‹ › navigation, rather than a row of status tabs. All three
 * ultimately show the same checklist form (`DayTaskChecklist`) for whichever
 * single day is in focus — week and month just add a picker (a strip of
 * days, a calendar grid) above it. Status still matters —
 * `pending_confirm` tasks get a confirm/reject row instead of a checkbox,
 * and `cancelled`/`rejected` ones move to the collapsed "Đã đóng" panel —
 * but it's no longer the primary way to slice the list.
 */
export function TasksPage() {
    const {
        tasks,
        isLoading,
        error,
        fetchAll,
        createTask,
        confirmTask,
        rejectTask,
        toggleTaskDone,
        completeTaskCascade,
        renameTask,
        setTaskDueDate,
        updateTaskDetail,
        restoreTask,
        deleteTask,
    } = useTasksPage()
    const { confirm, dialog } = useConfirmDialog()
    const toast = useToast()

    // DESIGN 10.2 — màn **Việc** có phạm vi *dự án đang mở*; màn **Hôm nay**
    // thì không, và sự bất đối xứng đó là chủ ý. Nếu Hôm nay cũng lọc theo
    // dự án, người dùng phải tự nhớ đi qua từng dự án để biết mình cần làm
    // gì — đúng công việc Cortex sinh ra để bỏ đi. Xếp hạng ở 7.1 chỉ có
    // nghĩa khi nó nhìn được toàn bộ.
    // Phạm vi đến từ bộ chuyển trên sidebar — trang này chỉ *đọc* nó.
    // Đặt một bộ chuyển thứ hai ở đây sẽ là hai chỗ đổi cùng một thứ, và
    // người dùng phải đoán cái nào thắng.
    const projects = useProjectStore((state) => state.projects)
    const openProjectId = useProjectStore((state) => state.openProjectId)
    const fetchProjects = useProjectStore((state) => state.fetchAll)
    const hasLoadedProjects = useProjectStore((state) => state.hasLoaded)
    const currentProjectName = projects.find((p) => p.id === openProjectId)?.name ?? null

    useEffect(() => {
        if (!hasLoadedProjects) void fetchProjects()
    }, [hasLoadedProjects, fetchProjects])

    const [taskView, setTaskView] = useState<TaskViewMode>('day')
    const [dayDate, setDayDate] = useState<string>(todayIso())
    const [weekReference, setWeekReference] = useState<Date>(() => new Date())
    const [weekSelectedDate, setWeekSelectedDate] = useState<string>(todayIso())
    const [monthReference, setMonthReference] = useState<Date>(() => new Date())
    const [monthSelectedDate, setMonthSelectedDate] = useState<string>(todayIso())

    const [addingTask, setAddingTask] = useState(false)
    const [busyTaskId, setBusyTaskId] = useState<string | null>(null)
    const [showClosed, setShowClosed] = useState(false)
    const [showCompleted, setShowCompleted] = useState(true)

    // `done` tasks move out of the day/week/month grid and into
    // `CompletedTasksPanel` below the moment they're ticked — that panel is
    // the one place to browse (and un-tick) them. No date-nav of its own:
    // it shares `dayDate`, the same day the "Hôm nay" tab already navigates,
    // so there's one date control for the page, not two drifting in
    // parallel. Filtered by `completed_at`, converted to *local* calendar
    // day via `localDateOfUtcTimestamp` — the backend stores it as a naive
    // UTC instant, so comparing the raw string (`dateOnly`) reads off the
    // wrong day whenever local time and UTC disagree on today's date
    // (anywhere east of UTC, that's most of every evening).
    // Lọc một lần ở đây thay vì ở từng danh sách bên dưới: mọi khung nhìn
    // của trang này (ngày/tuần/tháng, đã xong, đã đóng) phải nói về cùng
    // một dự án, nếu không "3 việc đang mở" ở chỗ này và danh sách ở chỗ
    // kia sẽ đếm hai tập khác nhau.
    //
    // `openProjectId === null` (chưa có dự án nào) hiện tất cả — một màn
    // hình trống không nói được vì sao nó trống là tệ hơn.
    const scopedTasks = useMemo(
        () => (openProjectId ? tasks.filter((t) => t.project_id === openProjectId) : tasks),
        [tasks, openProjectId],
    )
    const openTasks = useMemo(() => scopedTasks.filter((t) => isLiveTask(t) && t.status !== 'done'), [scopedTasks])
    const completedTasks = useMemo(() => scopedTasks.filter((t) => t.status === 'done'), [scopedTasks])
    const completedTasksOnDate = useMemo(
        () => completedTasks.filter((t) => t.completed_at && localDateOfUtcTimestamp(t.completed_at) === dayDate),
        [completedTasks, dayDate],
    )
    const closedTasks = useMemo(
        () => scopedTasks.filter((t) => t.status === 'cancelled' || t.status === 'rejected'),
        [scopedTasks],
    )

    const handleDeleteTask = async (task: TaskWire) => {
        const ok = await confirm({
            title: 'Xoá việc',
            message: `Xoá "${task.title}"?`,
            confirmLabel: 'Xoá',
            cancelLabel: 'Huỷ',
        })
        if (!ok) return
        setBusyTaskId(task.id)
        try {
            await deleteTask(task.id)
            toast.show({ message: `Đã xoá "${task.title}".` })
        } catch {
            toast.show({ kind: 'error', message: 'Không xoá được việc này. Thử lại sau.' })
        } finally {
            setBusyTaskId(null)
        }
    }

    const withBusy = async (taskId: string, action: () => Promise<unknown>) => {
        setBusyTaskId(taskId)
        try {
            await action()
        } finally {
            setBusyTaskId(null)
        }
    }

    const taskActions: TaskActions = {
        busyTaskId,
        onConfirm: (t) => void withBusy(t.id, () => confirmTask(t.id)),
        onReject: (t) => void withBusy(t.id, () => rejectTask(t.id)),
        onToggle: (t) => void toggleTaskWithCascade({
            task: t, allTasks: tasks, toggle: toggleTaskDone, completeCascade: completeTaskCascade, confirm,
        }),
        onRename: renameTask,
        onSetDueDate: setTaskDueDate,
        onUpdateDetail: updateTaskDetail,
        onRemove: (t) => void handleDeleteTask(t),
        onDetailClose: () => void fetchAll(),
    }

    return (
        <>
        <div className="today-panel tasks-page">
            <header className="tasks-page-header">
                <h1 className="tasks-page-title">Việc cần làm</h1>
                <p className="tasks-page-subtitle">
                    {currentProjectName
                        ? `Việc trong ${currentProjectName} — đổi dự án ở bộ chuyển trên sidebar.`
                        : 'Toàn bộ việc cần làm — không chỉ những gì "Hôm nay" xếp hạng là cần làm ngay.'}
                </p>
            </header>

            {error && <p className="tasks-page-error">{error}</p>}

            <section className="tasks-page-section">
                <div className="tasks-page-section-header">
                    <div>
                        {/* The page <h1> right above already says "Việc cần
                            làm"; repeating it 60px lower was two headings for
                            one thing. Only the clarifying line survives. */}
                        <p className="tasks-page-section-subtitle">
                            Bao gồm việc do trò chuyện gợi ý, đang chờ bạn xác nhận.
                        </p>
                    </div>
                    <div className="tasks-page-tabs">
                        {([
                            ['day', 'Hôm nay'],
                            ['week', 'Tuần này'],
                            ['month', 'Tháng này'],
                        ] as const).map(([mode, label]) => (
                            <button
                                key={mode}
                                type="button"
                                className={clsx('tasks-page-tab', taskView === mode && 'is-active')}
                                onClick={() => setTaskView(mode)}
                            >
                                {label}
                            </button>
                        ))}
                    </div>
                </div>

                {addingTask ? (
                    <SubtaskCreatePanel
                        onCancel={() => setAddingTask(false)}
                        onCreate={async (input) => {
                            await createTask(input)
                            setAddingTask(false)
                        }}
                    />
                ) : (
                    <button
                        type="button"
                        className="task-detail-modal-checklist-add"
                        onClick={() => setAddingTask(true)}
                    >
                        <Plus size={14} />
                        <span>Thêm việc mới…</span>
                    </button>
                )}

                {isLoading ? null : taskView === 'day' ? (
                    <DayView dateIso={dayDate} onNavigate={setDayDate} tasks={openTasks} actions={taskActions} />
                ) : taskView === 'week' ? (
                    <WeekView
                        reference={weekReference}
                        onNavigate={(ref) => setWeekReference(ref)}
                        selectedDate={weekSelectedDate}
                        onSelectDate={setWeekSelectedDate}
                        tasks={openTasks}
                        actions={taskActions}
                    />
                ) : (
                    <MonthView
                        reference={monthReference}
                        onNavigate={(ref) => setMonthReference(ref)}
                        selectedDate={monthSelectedDate}
                        onSelectDate={setMonthSelectedDate}
                        tasks={openTasks}
                        actions={taskActions}
                    />
                )}

                <CompletedTasksPanel
                    totalCount={completedTasks.length}
                    tasks={completedTasksOnDate}
                    isOpen={showCompleted}
                    onToggle={() => setShowCompleted((v) => !v)}
                    dateIso={dayDate}
                    actions={taskActions}
                />

                <ClosedTasksPanel
                    tasks={closedTasks}
                    isOpen={showClosed}
                    onToggle={() => setShowClosed((v) => !v)}
                    busyTaskId={busyTaskId}
                    onRestore={(t) => void withBusy(t.id, () => restoreTask(t.id))}
                    onRemove={(t) => void handleDeleteTask(t)}
                />
            </section>
        </div>
        {dialog}
        </>
    )
}

/** The ‹ label › row every view (day/week/month) navigates with. */
function DateNav({
    label,
    onPrev,
    onNext,
    onToday,
}: {
    label: string
    onPrev: () => void
    onNext: () => void
    /** Present only when the view isn't already on today/this week/this
     * month — a jump-back shortcut rather than clutter that's always there. */
    onToday?: () => void
}) {
    return (
        <div className="tasks-page-date-nav">
            <button type="button" className="tasks-page-mini-btn" aria-label="Trước" onClick={onPrev}>
                <ChevronLeft size={14} />
            </button>
            <span className="tasks-page-date-nav-label">{label}</span>
            <button type="button" className="tasks-page-mini-btn" aria-label="Sau" onClick={onNext}>
                <ChevronRight size={14} />
            </button>
            {onToday && (
                // Was "Hôm nay" — identical to the segmented tab's label just
                // above it, even though this button jumps the date navigator
                // back to the current day/week/month while the tab switches
                // which of those three it's viewing. Two controls saying the
                // same word for two different actions read as one confusing
                // control; "Hiện tại" (current) reads naturally for all three
                // view modes without colliding with the tab text.
                <button type="button" className="tasks-page-date-nav-today" onClick={onToday}>
                    Hiện tại
                </button>
            )}
        </div>
    )
}

/** A task the extraction pipeline suggested — a checkbox doesn't fit here,
 * it needs an explicit yes/no. */
function PendingConfirmRow({
    task,
    busy,
    onConfirm,
    onReject,
    compact = false,
}: {
    task: TaskWire
    busy: boolean
    onConfirm: () => void
    onReject: () => void
    compact?: boolean
}) {
    return (
        <li className={clsx('tasks-page-pending-row', compact && 'is-compact')}>
            <span className="tasks-page-pending-title">{task.title}</span>
            <div className="tasks-page-pending-actions">
                <button type="button" className="tasks-page-mini-btn" disabled={busy} title="Xác nhận" onClick={onConfirm}>
                    <Check size={12} />
                </button>
                <button type="button" className="tasks-page-mini-btn" disabled={busy} title="Từ chối" onClick={onReject}>
                    <X size={12} />
                </button>
            </div>
        </li>
    )
}

/**
 * The one checklist form used everywhere a single day's tasks need
 * rendering: the day tab itself, and the panel that appears below the week
 * strip / month grid once a date is picked. `pending_confirm` tasks get
 * their own row (no checkbox fits a suggestion); everything else is a
 * `TaskChecklistRow` — tick to complete, click the title for the detail
 * view, priority glyph for a quick priority change.
 */
function DayTaskChecklist({
    tasks,
    actions,
    emptyLabel = 'Không có việc nào.',
}: {
    tasks: TaskWire[]
    actions: TaskActions
    emptyLabel?: string
}) {
    const pending = tasks.filter((t) => t.status === 'pending_confirm')
    const live = tasks.filter((t) => t.status !== 'pending_confirm')

    if (tasks.length === 0) {
        return <p className="tasks-page-empty">{emptyLabel}</p>
    }

    return (
        <div className="tasks-page-day-view">
            {pending.length > 0 && (
                <ul className="tasks-page-pending-list">
                    {pending.map((t) => (
                        <PendingConfirmRow
                            key={t.id}
                            task={t}
                            busy={actions.busyTaskId === t.id}
                            onConfirm={() => actions.onConfirm(t)}
                            onReject={() => actions.onReject(t)}
                        />
                    ))}
                </ul>
            )}
            {live.length > 0 && (
                <ul className="today-checklist-list">
                    {flattenTaskTree(live).map(({ task: t, depth, isLast, guides }) => (
                        <TaskChecklistRow
                            key={t.id}
                            task={t}
                            depth={depth}
                            isLast={isLast}
                            guides={guides}
                            onToggle={() => actions.onToggle(t)}
                            onRename={(title) => actions.onRename(t.id, title)}
                            onSetDueDate={(date) => actions.onSetDueDate(t.id, date)}
                            onUpdateDetail={(patch) => actions.onUpdateDetail(t.id, patch)}
                            onRemove={() => actions.onRemove(t)}
                            onDetailClose={actions.onDetailClose}
                        />
                    ))}
                </ul>
            )}
        </div>
    )
}

function DayView({
    dateIso,
    onNavigate,
    tasks,
    actions,
}: {
    dateIso: string
    onNavigate: (iso: string) => void
    tasks: TaskWire[]
    actions: TaskActions
}) {
    const isToday = dateIso === todayIso()
    // Only "today" gets the forgiving overdue+undated bucket — a day you've
    // navigated to (past or future) shows exactly what's due that day, or
    // browsing to next Tuesday would show every undated task in the list.
    const filtered = useMemo(
        () => (isToday
            ? tasks.filter((t) => isVisibleToday(t))
            : tasksDueOn(tasks, fromIso(dateIso))),
        [tasks, dateIso, isToday],
    )

    return (
        <div>
            <DateNav
                label={formatDate(dateIso) ?? dateIso}
                onPrev={() => onNavigate(shiftIsoDate(dateIso, -1))}
                onNext={() => onNavigate(shiftIsoDate(dateIso, 1))}
                onToday={!isToday ? () => onNavigate(todayIso()) : undefined}
            />
            <DayTaskChecklist
                tasks={filtered}
                actions={actions}
                emptyLabel={isToday ? 'Không có việc nào cho hôm nay.' : 'Không có việc nào ngày này.'}
            />
        </div>
    )
}

function WeekView({
    reference,
    onNavigate,
    selectedDate,
    onSelectDate,
    tasks,
    actions,
}: {
    reference: Date
    onNavigate: (next: Date) => void
    selectedDate: string
    onSelectDate: (iso: string) => void
    tasks: TaskWire[]
    actions: TaskActions
}) {
    const days = useMemo(() => weekDays(reference), [reference])
    const countByDate = useMemo(() => {
        const counts = new Map<string, number>()
        for (const t of tasks) {
            if (!t.due_date) continue
            const day = dateOnly(t.due_date)
            counts.set(day, (counts.get(day) ?? 0) + 1)
        }
        return counts
    }, [tasks])
    const isCurrentWeek = days.some((d) => isTodayDate(d))
    const selectedTasks = useMemo(
        () => tasksDueOn(tasks, fromIso(selectedDate)),
        [tasks, selectedDate],
    )

    return (
        <div className="tasks-page-week-view">
            <DateNav
                label={`${formatShort(days[0])} – ${formatShort(days[6])}`}
                onPrev={() => onNavigate(shiftWeek(reference, -1))}
                onNext={() => onNavigate(shiftWeek(reference, 1))}
                onToday={!isCurrentWeek ? () => { onNavigate(new Date()); onSelectDate(todayIso()) } : undefined}
            />
            <div className="tasks-page-week-strip">
                {days.map((day) => {
                    const iso = toIso(day)
                    const count = countByDate.get(iso) ?? 0
                    return (
                        <button
                            key={iso}
                            type="button"
                            className={clsx(
                                'tasks-page-week-day-btn',
                                isTodayDate(day) && 'is-today',
                                selectedDate === iso && 'is-selected',
                            )}
                            onClick={() => onSelectDate(iso)}
                        >
                            <span className="tasks-page-week-day-btn-label">{weekdayLabel(day)}</span>
                            <span className="tasks-page-week-day-btn-date">{iso.slice(8, 10)}</span>
                            <span className={clsx('tasks-page-week-day-btn-count', count === 0 && 'is-zero')}>
                                {count}
                            </span>
                        </button>
                    )
                })}
            </div>
            <DayTaskChecklist tasks={selectedTasks} actions={actions} emptyLabel="Không có việc nào ngày này." />
        </div>
    )
}

function MonthView({
    reference,
    onNavigate,
    selectedDate,
    onSelectDate,
    tasks,
    actions,
}: {
    reference: Date
    onNavigate: (next: Date) => void
    selectedDate: string
    onSelectDate: (iso: string) => void
    tasks: TaskWire[]
    actions: TaskActions
}) {
    const days = useMemo(() => monthGridDays(reference), [reference])
    const countByDate = useMemo(() => {
        const counts = new Map<string, number>()
        for (const t of tasks) {
            if (!t.due_date) continue
            const day = dateOnly(t.due_date)
            counts.set(day, (counts.get(day) ?? 0) + 1)
        }
        return counts
    }, [tasks])
    const isCurrentMonth = isInCurrentMonth(new Date(), reference)
    const selectedTasks = useMemo(
        () => tasksDueOn(tasks, fromIso(selectedDate)),
        [tasks, selectedDate],
    )

    return (
        <div className="tasks-page-month-view">
            <DateNav
                label={reference.toLocaleDateString('vi-VN', { month: 'long', year: 'numeric' })}
                onPrev={() => onNavigate(previousMonth(reference))}
                onNext={() => onNavigate(nextMonth(reference))}
                onToday={!isCurrentMonth ? () => { onNavigate(new Date()); onSelectDate(todayIso()) } : undefined}
            />
            <div className="tasks-page-month-grid is-compact">
                {['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'].map((label) => (
                    <div key={label} className="tasks-page-month-weekday">{label}</div>
                ))}
                {days.map((day) => {
                    const iso = toIso(day)
                    const count = countByDate.get(iso) ?? 0
                    return (
                        <button
                            key={iso}
                            type="button"
                            className={clsx(
                                'tasks-page-month-cell',
                                !isInCurrentMonth(day, reference) && 'is-outside',
                                isTodayDate(day) && 'is-today',
                                selectedDate === iso && 'is-selected',
                            )}
                            onClick={() => onSelectDate(iso)}
                        >
                            <span className="tasks-page-month-cell-day">{iso.slice(8, 10)}</span>
                            {count > 0 && <span className="tasks-page-month-cell-count">{count}</span>}
                        </button>
                    )
                })}
            </div>
            <div className="tasks-page-month-selected">
                <div className="tasks-page-month-selected-label">{formatDate(selectedDate)}</div>
                <DayTaskChecklist tasks={selectedTasks} actions={actions} emptyLabel="Không có việc nào ngày này." />
            </div>
        </div>
    )
}

/**
 * Where a task goes the moment it's ticked done — pulled out of the day/
 * week/month grid so a finished item doesn't keep sitting among the still-
 * open ones. No date-nav of its own: `dateIso` is the same `dayDate` the
 * "Hôm nay" tab navigates, so browsing a different day there filters this
 * panel too, instead of a second nav control drifting out of sync with the
 * first. Every row is still a real `TaskChecklistRow`: un-ticking it here is
 * the same toggle as anywhere else, so a task done by mistake goes straight
 * back to `todo`.
 */
function CompletedTasksPanel({
    totalCount,
    tasks,
    isOpen,
    onToggle,
    dateIso,
    actions,
}: {
    /** All-time completed count, shown on the collapsed toggle — stable
     * regardless of which day `dateIso` currently browses to. */
    totalCount: number
    tasks: TaskWire[]
    isOpen: boolean
    onToggle: () => void
    dateIso: string
    actions: TaskActions
}) {
    if (totalCount === 0) return null

    return (
        <div className="tasks-page-closed-panel">
            <button type="button" className="tasks-page-closed-toggle" onClick={onToggle}>
                <ChevronDown size={13} className={clsx('tasks-page-closed-chevron', isOpen && 'is-open')} />
                Đã hoàn thành ({totalCount})
            </button>
            {isOpen && (
                <>
                    <p className="tasks-page-completed-date-label">
                        Ngày {formatDate(dateIso) ?? dateIso}
                    </p>
                    <DayTaskChecklist
                        tasks={tasks}
                        actions={actions}
                        emptyLabel="Không có việc nào hoàn thành ngày này."
                    />
                </>
            )}
        </div>
    )
}

function ClosedTasksPanel({
    tasks,
    isOpen,
    onToggle,
    busyTaskId,
    onRestore,
    onRemove,
}: {
    tasks: TaskWire[]
    isOpen: boolean
    onToggle: () => void
    busyTaskId: string | null
    onRestore: (task: TaskWire) => void
    onRemove: (task: TaskWire) => void
}) {
    if (tasks.length === 0) return null

    return (
        <div className="tasks-page-closed-panel">
            <button type="button" className="tasks-page-closed-toggle" onClick={onToggle}>
                <ChevronDown size={13} className={clsx('tasks-page-closed-chevron', isOpen && 'is-open')} />
                Đã đóng ({tasks.length})
            </button>
            {isOpen && (
                <ul className="tasks-page-closed-list">
                    {tasks.map((t) => (
                        <li key={t.id} className="tasks-page-closed-row">
                            <span className="tasks-page-closed-title">{t.title}</span>
                            <span className={clsx('tasks-page-status-badge', `is-task-${t.status}`)}>
                                {CLOSED_STATUS_LABELS[t.status as 'cancelled' | 'rejected']}
                            </span>
                            <div className="tasks-page-closed-actions">
                                {t.status === 'cancelled' && (
                                    <button
                                        type="button"
                                        className="tasks-page-mini-btn"
                                        disabled={busyTaskId === t.id}
                                        title="Khôi phục"
                                        onClick={() => onRestore(t)}
                                    >
                                        <RotateCcw size={12} />
                                    </button>
                                )}
                                <button
                                    type="button"
                                    className="tasks-page-icon-btn"
                                    title="Xoá"
                                    disabled={busyTaskId === t.id}
                                    onClick={() => onRemove(t)}
                                >
                                    <Trash2 size={13} />
                                </button>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </div>
    )
}
