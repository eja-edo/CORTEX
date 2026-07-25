import { useState, useEffect, useRef, useCallback, type ReactNode } from 'react'
import { CheckCircle2, Clock3, MapPin, Tag, Trash2, X, Repeat } from 'lucide-react'
import { format } from 'date-fns'
import type { Schedule, ScheduleType } from '../types'
import { MarkdownField } from './MarkdownField'

const TYPE_LABELS: Record<string, string> = {
  CLASS: 'Class',
  DEADLINE: 'Deadline',
  EXAM: 'Exam',
  PERSONAL: 'Personal',
  CRON_EVENT: 'Cron',
}

const TYPE_OPTIONS: ScheduleType[] = ['CLASS', 'DEADLINE', 'EXAM', 'PERSONAL', 'CRON_EVENT']

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function toIsoDateTime(localDateTime: string): string {
  return new Date(localDateTime).toISOString()
}

function formatTimeRange(start: Date, end: Date): string {
  return `${format(start, 'HH:mm')} – ${format(end, 'HH:mm')}`
}

interface EventDetailModalProps {
  schedule: Schedule
  startDate: Date
  endDate: Date
  canEdit: boolean
  onUpdate: (item: Schedule, patch: Partial<Schedule>) => Promise<boolean>
  onToggleComplete: (item: Schedule) => Promise<void>
  onRemove: (id: string) => Promise<void>
  onClose: () => void
}

/**
 * Editor "chip" that swaps on double-click into an inline <input/>. Saves
 * on Enter / blur; cancels on Escape.
 */
function InlineTextInput({
  value,
  onSave,
  display,
  placeholder,
  ariaLabel,
  className,
  multiline,
}: {
  value: string
  display: ReactNode
  onSave: (next: string) => Promise<boolean>
  placeholder?: string
  ariaLabel?: string
  className?: string
  multiline?: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null)

  useEffect(() => {
    if (editing) {
      const el = inputRef.current
      if (el) {
        el.focus()
        if ('setSelectionRange' in el) {
          const len = (el as HTMLInputElement).value.length
          el.setSelectionRange(len, len)
        }
      }
    }
  }, [editing])

  const begin = useCallback(() => {
    setDraft(value)
    setEditing(true)
  }, [value])

  const commit = useCallback(async () => {
    const ok = await onSave(draft)
    if (ok === false) setDraft(value)
    setEditing(false)
  }, [draft, value, onSave])

  const cancel = useCallback(() => {
    setDraft(value)
    setEditing(false)
  }, [value])

  if (editing) {
    const sharedProps = {
      value: draft,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
        setDraft(e.target.value),
      onBlur: commit,
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault()
          commit()
        }
        if (e.key === 'Escape') cancel()
      },
      placeholder,
      'aria-label': ariaLabel,
      className,
    }
    return multiline ? (
      <textarea ref={inputRef as React.RefObject<HTMLTextAreaElement>} {...sharedProps} rows={2} />
    ) : (
      <input ref={inputRef as React.RefObject<HTMLInputElement>} {...sharedProps} />
    )
  }

  return (
    <span
      className={`inline-editable ${className ?? ''}`.trim()}
      onDoubleClick={begin}
      title="Double-click to edit"
    >
      {display}
    </span>
  )
}

function InlineSelect<T extends string>({
  value,
  options,
  onSave,
  display,
}: {
  value: T
  options: { value: T; label: string }[]
  onSave: (next: T) => Promise<boolean>
  display: ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(value)

  const begin = useCallback(() => {
    setDraft(value)
    setEditing(true)
  }, [value])

  const commit = useCallback(async () => {
    const ok = await onSave(draft)
    if (ok === false) setDraft(value)
    setEditing(false)
  }, [draft, value, onSave])

  const cancel = useCallback(() => {
    setDraft(value)
    setEditing(false)
  }, [value])

  if (editing) {
    return (
      <select
        className="editing-select"
        value={draft}
        onChange={e => setDraft(e.target.value as T)}
        onBlur={commit}
        onKeyDown={e => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') cancel()
        }}
        autoFocus
      >
        {options.map(opt => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
    )
  }

  return (
    <span onDoubleClick={begin} title="Double-click to edit">
      {display}
    </span>
  )
}

function InlineTimeRange({
  start,
  end,
  onSave,
  display,
}: {
  start: Date
  end: Date
  onSave: (next: { start: string; end: string }) => Promise<boolean>
  display: ReactNode
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({
    start: toLocalInputDateTime(start),
    end: toLocalInputDateTime(end),
  })
  const startRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (editing) {
      startRef.current?.focus()
    }
  }, [editing])

  const begin = useCallback(() => {
    setDraft({
      start: toLocalInputDateTime(start),
      end: toLocalInputDateTime(end),
    })
    setEditing(true)
  }, [start, end])

  const commit = useCallback(async () => {
    if (!draft.start || !draft.end) {
      setEditing(false)
      return
    }
    const ok = await onSave(draft)
    if (ok === false) setDraft({ start: toLocalInputDateTime(start), end: toLocalInputDateTime(end) })
    setEditing(false)
  }, [draft, start, end, onSave])

  const cancel = useCallback(() => {
    setDraft({ start: toLocalInputDateTime(start), end: toLocalInputDateTime(end) })
    setEditing(false)
  }, [start, end])

  if (editing) {
    return (
      <span className="time-editor">
        <input
          ref={startRef}
          type="datetime-local"
          value={draft.start}
          onChange={e => setDraft({ ...draft, start: e.target.value })}
          onKeyDown={e => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') cancel()
          }}
        />
        <span aria-hidden>→</span>
        <input
          type="datetime-local"
          value={draft.end}
          onChange={e => setDraft({ ...draft, end: e.target.value })}
          onBlur={commit}
          onKeyDown={e => {
            if (e.key === 'Enter') commit()
            if (e.key === 'Escape') cancel()
          }}
        />
      </span>
    )
  }

  return (
    <span onDoubleClick={begin} title="Double-click to edit">
      {display}
    </span>
  )
}

export function EventDetailModal({
  schedule,
  startDate,
  endDate,
  canEdit,
  onUpdate,
  onToggleComplete,
  onRemove,
  onClose,
}: EventDetailModalProps) {
  // Snapshot for inline-editing — we hold a local copy so the parent's
  // `schedules` array doesn't have to update instantly for the editor to
  // show new drafts.
  const [draft, setDraft] = useState<Schedule>(schedule)

  // If the parent selects a different schedule, re-seed the draft.
  useEffect(() => {
    setDraft(schedule)
  }, [schedule])

  const patch = async (changes: Partial<Schedule>): Promise<boolean> => {
    if (!canEdit) return false
    const ok = await onUpdate(draft, changes)
    if (ok) setDraft({ ...draft, ...changes })
    return ok
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-area">
            <InlineSelect<ScheduleType>
              value={draft.type}
              options={TYPE_OPTIONS.map(t => ({ value: t, label: TYPE_LABELS[t] ?? t }))}
              onSave={(next) => patch({ type: next })}
              display={
                <div className={`modal-event-type-badge badge-${draft.type}`}>
                  {TYPE_LABELS[draft.type] ?? draft.type}
                </div>
              }
            />
            <InlineTextInput
              value={draft.title}
              className="modal-title-input"
              ariaLabel="Title"
              onSave={async (next) => {
                if (!next.trim()) return false
                return patch({ title: next.trim() })
              }}
              display={<div className="modal-title">{draft.title}</div>}
            />
          </div>
          <button type="button" className="modal-close" onClick={onClose}>
            <X size={15} />
          </button>
        </div>

        <div className="modal-body">
          <div className="modal-meta-list">
            <div className="modal-meta-row">
              <Clock3 size={14} className="modal-meta-icon" />
              <InlineTimeRange
                start={startDate}
                end={endDate}
                onSave={(next) =>
                  patch({
                    start_time: toIsoDateTime(next.start),
                    end_time: toIsoDateTime(next.end),
                  })
                }
                display={
                  <span className="modal-meta-text">
                    {format(startDate, 'EEEE, MMM d, yyyy')} · {formatTimeRange(startDate, endDate)}
                  </span>
                }
              />
            </div>

            {/* Recurrence indicator — read-only display, no inline edit yet. */}
            {draft.recurrence && draft.recurrence.freq !== 'NONE' && (
              <div className="modal-meta-row">
                <Repeat size={14} className="modal-meta-icon" />
                <span className="modal-meta-text">
                  {draft.recurrence.freq === 'DAILY' && 'Daily'}
                  {draft.recurrence.freq === 'WEEKLY' && 'Weekly'}
                  {draft.recurrence.freq === 'MONTHLY' && 'Monthly'}
                  {draft.recurrence.interval && draft.recurrence.interval > 1 && ` every ${draft.recurrence.interval}`}
                </span>
              </div>
            )}

            <div className="modal-meta-row">
              <MapPin size={14} className="modal-meta-icon" />
              <InlineTextInput
                value={draft.location ?? ''}
                className="modal-meta-input"
                ariaLabel="Location"
                placeholder="Phòng hoặc Link Zoom"
                onSave={async (next) => {
                  const trimmed = next.trim()
                  return patch({ location: trimmed || null })
                }}
                display={
                  <span className="modal-meta-text">
                    {draft.location || <em className="modal-meta-placeholder">Add location…</em>}
                  </span>
                }
              />
            </div>

            <div className="modal-meta-row">
              <Tag size={14} className="modal-meta-icon" />
              <span className="modal-meta-text" style={{ color: 'var(--text-tertiary)' }}>
                {draft.is_completed ? 'Completed' : 'In progress'}
              </span>
            </div>
          </div>

          <div className="modal-description">
            <div className="modal-description-label">Notes</div>
            <MarkdownField
              className="input-field"
              rows={3}
              value={draft.description ?? ''}
              onChange={(next) => setDraft({ ...draft, description: next })}
              onImmediateChange={(next) => {
                const trimmed = next.trim()
                void patch({ description: trimmed || null })
              }}
              onBlur={() => {
                if (draft.description !== schedule.description) {
                  const trimmed = (draft.description ?? '').trim()
                  void patch({ description: trimmed || null })
                }
              }}
              placeholder="Nội dung tóm tắt…"
              ariaLabel="Notes (markdown)"
            />
          </div>
        </div>

        <div className="modal-footer">
          <button
            type="button"
            className="btn btn-danger"
            onClick={async () => { if (schedule.id) { await onRemove(schedule.id); } onClose() }}
          >
            <Trash2 size={13} /> Delete
          </button>
          <div className="modal-footer-right">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Close
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={async () => { await onToggleComplete(schedule); onClose() }}
            >
              <CheckCircle2 size={13} />
              {schedule.is_completed ? 'Mark in progress' : 'Mark complete'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
