import { useEffect, useState } from 'react'
import { Calendar, CheckCircle2, Circle, Clock3, Layers, MapPin, Repeat, Trash2, X } from 'lucide-react'
import type { EditScope, Schedule, ScheduleType } from '../types'
import { parseServerDateTime } from '../utils/calendarItems'
import { MarkdownField } from './MarkdownField'
import { EventChecklist } from './EventChecklist'
import { useEscapeToClose } from '../hooks/useEscapeToClose'
import { useEditScopeDialog } from '../hooks/useEditScopeDialog'

// Field edits (title/description/location/time) on a recurring event ask
// which occurrences this applies to — completing/un-completing never does,
// it's always scoped to the occurrence being viewed (see `toggleComplete`).
const EDIT_SCOPE_OPTIONS: { scope: EditScope; label: string }[] = [
  { scope: 'this_only', label: 'Chỉ sự kiện này' },
  { scope: 'all', label: 'Toàn bộ chuỗi lặp' },
]

const TYPE_LABELS: Record<ScheduleType, string> = {
  CLASS: 'Lớp học (Class)',
  EXAM: 'Hội chẩn (Exam)',
  PERSONAL: 'Cá nhân (Personal)',
  DEADLINE: 'Deadline',
  CRON_EVENT: 'Cron',
}

const TYPE_OPTIONS: ScheduleType[] = ['CLASS', 'EXAM', 'PERSONAL', 'DEADLINE', 'CRON_EVENT']

const RECURRENCE_LABELS: Record<string, string> = {
  DAILY: 'Hàng ngày',
  WEEKLY: 'Hàng tuần',
  MONTHLY: 'Hàng tháng',
}

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function toIsoDateTime(localDateTime: string): string {
  return new Date(localDateTime).toISOString()
}

interface EventDetailModalProps {
  schedule: Schedule
  canEdit: boolean
  onUpdate: (item: Schedule, patch: Partial<Schedule>) => Promise<boolean>
  onToggleComplete: (item: Schedule) => Promise<void>
  // Recurring-only path: every occurrence without its own exception shares
  // the root's id, so onUpdate/onToggleComplete would silently change every
  // occurrence at once. Optional so a caller that never shows recurring
  // events (none currently) doesn't have to wire it.
  onUpdateInstance?: (item: Schedule, editScope: EditScope, patch: Partial<Schedule>) => Promise<boolean>
  onRemove: (id: string) => Promise<void>
  onClose: () => void
}

/**
 * Viewing/editing an existing event — same shell as `ScheduleForm`
 * (`.task-detail-modal-*`) and `TaskDetailModal`: big borderless
 * title/description on the left, a "Thuộc tính" property list on the
 * right, checklist under the description. Unlike the create form there's
 * no submit step — every property commits on change/blur, same as
 * `TaskDetailModal`, since this is editing something that already exists.
 */
export function EventDetailModal({
  schedule,
  canEdit,
  onUpdate,
  onToggleComplete,
  onUpdateInstance,
  onRemove,
  onClose,
}: EventDetailModalProps) {
  useEscapeToClose(onClose)
  const { promptEditScope, dialog: editScopeDialog } = useEditScopeDialog()
  // Snapshot for editing — we hold a local copy so the parent's `schedules`
  // array doesn't have to update instantly for the fields to show new drafts.
  const [draft, setDraft] = useState<Schedule>(schedule)
  const [titleInput, setTitleInput] = useState(schedule.title)
  const [startLocal, setStartLocal] = useState(() => toLocalInputDateTime(parseServerDateTime(schedule.start_time)))
  const [endLocal, setEndLocal] = useState(() => toLocalInputDateTime(parseServerDateTime(schedule.end_time)))

  // `schedule` is a stable reference for as long as this event stays open
  // (`CalendarView` only replaces it via a fresh click, never on its own
  // re-renders) — so this only re-seeds on a genuine switch to a different
  // event, not on every parent re-render. It used to also depend on
  // `startDate`/`endDate` Date-object props that CalendarView recomputed
  // (new reference, same value) on every render; that made this effect
  // re-fire constantly and stomp `draft` back to the pre-edit snapshot —
  // a field could save successfully and still visibly "revert" on blur,
  // only showing the real value after closing and reopening the modal.
  useEffect(() => {
    setDraft(schedule)
    setTitleInput(schedule.title)
    setStartLocal(toLocalInputDateTime(parseServerDateTime(schedule.start_time)))
    setEndLocal(toLocalInputDateTime(parseServerDateTime(schedule.end_time)))
  }, [schedule])

  const patch = async (changes: Partial<Schedule>): Promise<boolean> => {
    if (!canEdit) return false
    if (draft.is_recurring && onUpdateInstance) {
      const scope = await promptEditScope({
        title: 'Sự kiện lặp lại',
        message: 'Áp dụng thay đổi này cho buổi nào?',
        options: EDIT_SCOPE_OPTIONS,
      })
      if (!scope) return false
      const ok = await onUpdateInstance(draft, scope, changes)
      if (ok) setDraft({ ...draft, ...changes })
      return ok
    }
    const ok = await onUpdate(draft, changes)
    if (ok) setDraft({ ...draft, ...changes })
    return ok
  }

  const toggleComplete = async () => {
    // Completing/un-completing never asks — it always applies to the
    // occurrence being viewed, silently. Only a field edit (title,
    // description, location, time) asks whether it's just this occurrence
    // or the whole series (see `patch`).
    if (draft.is_recurring && onUpdateInstance) {
      const ok = await onUpdateInstance(draft, 'this_only', { is_completed: !draft.is_completed })
      if (ok) setDraft((d) => ({ ...d, is_completed: !d.is_completed }))
      return
    }
    setDraft((d) => ({ ...d, is_completed: !d.is_completed }))
    void onToggleComplete(schedule)
  }

  const commitTitle = async () => {
    const trimmed = titleInput.trim()
    if (trimmed && trimmed !== draft.title) {
      await patch({ title: trimmed })
    } else {
      setTitleInput(draft.title)
    }
  }

  const commitTime = async () => {
    if (!startLocal || !endLocal) return
    const nextStart = toIsoDateTime(startLocal)
    const nextEnd = toIsoDateTime(endLocal)
    if (nextStart === draft.start_time && nextEnd === draft.end_time) return
    await patch({ start_time: nextStart, end_time: nextEnd })
  }

  const commitLocation = async () => {
    const trimmed = (draft.location ?? '').trim()
    if (trimmed !== (schedule.location ?? '')) {
      await patch({ location: trimmed || null })
    }
  }

  const recurrenceLabel = draft.recurrence && draft.recurrence.freq !== 'NONE'
    ? `${RECURRENCE_LABELS[draft.recurrence.freq] ?? draft.recurrence.freq}`
      + (draft.recurrence.interval && draft.recurrence.interval > 1 ? ` · mỗi ${draft.recurrence.interval}` : '')
    : null

  return (
    <>
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal task-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div className="task-detail-modal-topbar">
          <button
            type="button"
            className="modal-close"
            onClick={async () => { if (schedule.id) { await onRemove(schedule.id) } onClose() }}
            aria-label="Xoá"
            title="Xoá"
          >
            <Trash2 size={15} />
          </button>
          <button type="button" className="modal-close" onClick={onClose} aria-label="Đóng">
            <X size={15} />
          </button>
        </div>

        <div className="task-detail-modal-body">
          <div className="task-detail-modal-columns">
            <div className="task-detail-modal-main">
              <input
                className="task-detail-modal-title-input"
                value={titleInput}
                aria-label="Tên sự kiện"
                disabled={!canEdit}
                onChange={(e) => setTitleInput(e.target.value)}
                onBlur={() => void commitTitle()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') { e.preventDefault(); void commitTitle() }
                  if (e.key === 'Escape') setTitleInput(draft.title)
                }}
              />
              <MarkdownField
                className="task-detail-modal-description-input"
                value={draft.description ?? ''}
                onChange={(next) => setDraft((d) => ({ ...d, description: next }))}
                onImmediateChange={(next) => {
                  void patch({ description: next.trim() || null })
                }}
                onBlur={() => {
                  if (draft.description !== schedule.description) {
                    void patch({ description: draft.description?.trim() || null })
                  }
                }}
                placeholder="Thêm mô tả…"
                ariaLabel="Mô tả (markdown)"
              />

              {/*
                Checklist (2.6). Reads `tasks WHERE related_event_id = id` — it
                is NOT parsed out of the description above, and nothing it does
                is written back there. Description stays prose; checklist state
                lives in `tasks`, where a due date, a status, a priority and a
                description can actually be stored.
              */}
              <EventChecklist
                eventId={schedule.id}
                eventEndTime={schedule.end_time}
                occurrenceStartTime={draft.original_start_time ?? draft.start_time}
                isRecurring={draft.is_recurring}
                promptEditScope={promptEditScope}
              />
            </div>

            <div className="task-detail-modal-sidebar">
              <div className="task-detail-modal-sidebar-label">Thuộc tính</div>

              <button
                type="button"
                className="task-detail-modal-property"
                disabled={!canEdit}
                onClick={() => void toggleComplete()}
              >
                {draft.is_completed
                  ? <CheckCircle2 size={14} style={{ color: 'var(--green, #16a34a)' }} />
                  : <Circle size={14} style={{ color: 'var(--text-tertiary)' }} />}
                <span>{draft.is_completed ? 'Đã xong' : 'Đang diễn ra'}</span>
              </button>

              <label className="task-detail-modal-property">
                <Layers size={14} />
                <select
                  className="task-detail-modal-property-field"
                  value={draft.type}
                  aria-label="Phân loại"
                  disabled={!canEdit}
                  onChange={(e) => void patch({ type: e.target.value as ScheduleType })}
                >
                  {TYPE_OPTIONS.map((t) => (
                    <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                  ))}
                </select>
              </label>

              <label className="task-detail-modal-property">
                <MapPin size={14} />
                <input
                  type="text"
                  className="task-detail-modal-property-field"
                  value={draft.location ?? ''}
                  placeholder="Địa điểm"
                  aria-label="Địa điểm"
                  disabled={!canEdit}
                  onChange={(e) => setDraft((d) => ({ ...d, location: e.target.value }))}
                  onBlur={() => void commitLocation()}
                />
              </label>

              <label className="task-detail-modal-property">
                <Calendar size={14} />
                <span className="task-detail-modal-property-label">Từ</span>
                <input
                  type="datetime-local"
                  className="task-detail-modal-property-field"
                  value={startLocal}
                  aria-label="Bắt đầu"
                  disabled={!canEdit}
                  onChange={(e) => setStartLocal(e.target.value)}
                  onBlur={() => void commitTime()}
                />
              </label>

              <label className="task-detail-modal-property">
                <Clock3 size={14} />
                <span className="task-detail-modal-property-label">Đến</span>
                <input
                  type="datetime-local"
                  className="task-detail-modal-property-field"
                  value={endLocal}
                  aria-label="Kết thúc"
                  disabled={!canEdit}
                  onChange={(e) => setEndLocal(e.target.value)}
                  onBlur={() => void commitTime()}
                />
              </label>

              {/* Read-only for now — set at creation (`ScheduleForm`), no
                  inline editor for an existing event's recurrence yet. */}
              {recurrenceLabel && (
                <div className="task-detail-modal-property" style={{ cursor: 'default' }}>
                  <Repeat size={14} />
                  <span>{recurrenceLabel}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
    {editScopeDialog}
    </>
  )
}
