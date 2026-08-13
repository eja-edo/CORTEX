import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Layers, MapPin, Calendar, Clock3, RefreshCw, Bell, Circle, Plus, Trash2, X } from 'lucide-react'
import { clsx } from 'clsx'

import type { Schedule, ScheduleType, RecurrenceRule, ReminderConfig, TaskPriority } from '../types'
import { RecurrenceConfig } from './RecurrenceConfig'
import { ReminderConfig as ReminderConfigComponent } from './ReminderConfig'
import { MarkdownField } from './MarkdownField'
import { PriorityIcon } from './PriorityIcon'
import { SubtaskCreatePanel } from './SubtaskCreatePanel'
import { useTaskStore } from '../stores/taskStore'

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function getNowRounded(): Date {
  const now = new Date()
  const minutes = now.getMinutes()
  const roundedMinutes = minutes < 30 ? 30 : 0
  const hoursAdd = minutes < 30 ? 0 : 1
  now.setMinutes(roundedMinutes, 0, 0)
  now.setHours(now.getHours() + hoursAdd)
  return now
}

type ChecklistDraft = { title: string; description: string | null; priority: TaskPriority | null }

interface ScheduleFormProps {
  onCreate: (schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>) => Promise<Schedule | null>
  /** If provided (e.g. from a calendar slot click), pre-fills start/end times */
  initialTimes?: { startDate: string; endDate: string } | null
  onClose?: () => void
}

/**
 * Create-event form, styled to match `TaskDetailModal` — big borderless
 * title/description on the left, a "Thuộc tính" property list on the
 * right — instead of the old boxed grid-row/time-box/pill layout. Shares
 * the `.task-detail-modal-*` classes directly rather than a parallel set,
 * so the two stay visually identical without duplicated CSS.
 *
 * Checklist items are held as plain drafts, not `Task`s — there's no event
 * id to attach `related_event_id` to until the event itself is created.
 * `handleSubmit` creates the event first, then walks the drafts creating
 * one task per item, linked to the new event.
 */
export function ScheduleForm({ onCreate, initialTimes, onClose }: ScheduleFormProps) {
  const createTask = useTaskStore((state) => state.createTask)
  const [title, setTitle] = useState('')
  const [type, setType] = useState<ScheduleType>('CLASS')
  const [startTime, setStartTime] = useState<string>(() => {
    if (initialTimes) return initialTimes.startDate
    return toLocalInputDateTime(getNowRounded())
  })
  const [endTime, setEndTime] = useState<string>(() => {
    if (initialTimes) return initialTimes.endDate
    const start = getNowRounded()
    start.setHours(start.getHours() + 1)
    return toLocalInputDateTime(start)
  })
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')

  const [recurrence, setRecurrence] = useState<RecurrenceRule | null>(null)
  const [reminders, setReminders] = useState<ReminderConfig[]>([])

  const [showRecurrence, setShowRecurrence] = useState(false)
  const [showReminders, setShowReminders] = useState(false)

  const [checklistDrafts, setChecklistDrafts] = useState<ChecklistDraft[]>([])
  const [addingChecklistItem, setAddingChecklistItem] = useState(false)

  const [formError, setFormError] = useState('')

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    if (!initialTimes) return
    setStartTime(initialTimes.startDate)
    setEndTime(initialTimes.endDate)
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [initialTimes])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setFormError('')

    if (!title.trim()) {
      setFormError('Cần có tiêu đề')
      return
    }

    if (!startTime || !endTime) {
      setFormError('Cần có thời gian bắt đầu và kết thúc')
      return
    }

    try {
      const created = await onCreate({
        title: title.trim(),
        type,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        location: location.trim() || null,
        description: description.trim() || null,
        recurrence,
        reminders,
      })
      if (!created) {
        setFormError('Tạo sự kiện thất bại')
        return
      }

      for (const draft of checklistDrafts) {
        await createTask({
          title: draft.title,
          description: draft.description,
          priority: draft.priority,
          related_event_id: created.id,
        })
      }

      onClose?.()
    } catch {
      setFormError('Tạo sự kiện thất bại')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="task-detail-modal-body">
      <div className="task-detail-modal-columns">
        <div className="task-detail-modal-main">
          {formError && <div className="form-error">{formError}</div>}

          <input
            type="text"
            className="task-detail-modal-title-input"
            value={title}
            onChange={e => setTitle(e.target.value)}
            placeholder="Tên sự kiện của bạn…"
            aria-label="Tên sự kiện"
            autoFocus
            required
          />
          <MarkdownField
            className="task-detail-modal-description-input"
            value={description}
            onChange={setDescription}
            placeholder="Thêm mô tả…"
            ariaLabel="Ghi chú thêm"
          />

          <div className="task-detail-modal-checklist">
            <div className="task-detail-modal-checklist-header">
              <span className="task-detail-modal-sidebar-label">Checklist</span>
              {checklistDrafts.length > 0 && (
                <span className="task-detail-modal-checklist-count">{checklistDrafts.length}</span>
              )}
            </div>

            {checklistDrafts.length > 0 && (
              <ul className="event-checklist-list">
                {checklistDrafts.map((draft, index) => (
                  <li key={index} className="today-checklist-row">
                    <span className="today-checklist-box" aria-hidden>
                      <Circle size={10} />
                    </span>
                    <PriorityIcon priority={draft.priority} />
                    <span className="today-checklist-title" style={{ cursor: 'default' }}>
                      {draft.title}
                    </span>
                    <button
                      type="button"
                      className="today-checklist-remove"
                      aria-label={`Xoá: ${draft.title}`}
                      onClick={() => setChecklistDrafts((items) => items.filter((_, i) => i !== index))}
                    >
                      <Trash2 size={12} />
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {addingChecklistItem ? (
              <SubtaskCreatePanel
                onCancel={() => setAddingChecklistItem(false)}
                onCreate={async (input) => {
                  setChecklistDrafts((items) => [...items, input])
                  setAddingChecklistItem(false)
                }}
              />
            ) : (
              <button
                type="button"
                className="task-detail-modal-checklist-add"
                onClick={() => setAddingChecklistItem(true)}
              >
                <Plus size={13} />
                <span>Thêm sub-issue</span>
              </button>
            )}
          </div>
        </div>

        <div className="task-detail-modal-sidebar">
          <div className="task-detail-modal-sidebar-label">Thuộc tính</div>

          <label className="task-detail-modal-property">
            <Layers size={14} />
            <select
              className="task-detail-modal-property-field"
              value={type}
              aria-label="Phân loại"
              onChange={e => setType(e.target.value as ScheduleType)}
            >
              <option value="CLASS">Lớp học (Class)</option>
              <option value="EXAM">Hội chẩn (Exam)</option>
              <option value="PERSONAL">Cá nhân (Personal)</option>
              <option value="DEADLINE">Deadline</option>
              <option value="CRON_EVENT">Cron</option>
            </select>
          </label>

          <label className="task-detail-modal-property">
            <MapPin size={14} />
            <input
              type="text"
              className="task-detail-modal-property-field"
              value={location}
              onChange={e => setLocation(e.target.value)}
              placeholder="Địa điểm"
              aria-label="Địa điểm"
            />
          </label>

          <label className="task-detail-modal-property">
            <Calendar size={14} />
            <span className="task-detail-modal-property-label">Từ</span>
            <input
              type="datetime-local"
              className="task-detail-modal-property-field"
              value={startTime}
              onChange={e => setStartTime(e.target.value)}
              aria-label="Bắt đầu"
              required
            />
          </label>

          <label className="task-detail-modal-property">
            <Clock3 size={14} />
            <span className="task-detail-modal-property-label">Đến</span>
            <input
              type="datetime-local"
              className="task-detail-modal-property-field"
              value={endTime}
              onChange={e => setEndTime(e.target.value)}
              aria-label="Kết thúc"
              required
            />
          </label>

          <button
            type="button"
            className={clsx('task-detail-modal-property', recurrence && 'is-active')}
            onClick={() => setShowRecurrence(s => !s)}
          >
            <RefreshCw size={14} />
            <span>{recurrence ? 'Lặp lại: bật' : 'Không lặp lại'}</span>
          </button>

          <button
            type="button"
            className={clsx('task-detail-modal-property', reminders.length > 0 && 'is-active')}
            onClick={() => setShowReminders(s => !s)}
          >
            <Bell size={14} />
            <span>{reminders.length > 0 ? `${reminders.length} nhắc nhở` : 'Không nhắc nhở'}</span>
          </button>

          <button type="submit" className="btn btn-primary task-detail-modal-submit">
            Tạo sự kiện
          </button>
        </div>
      </div>

      {((showRecurrence || recurrence) || (showReminders || reminders.length > 0)) && (
        <div className="task-detail-modal-panels">
          {(showRecurrence || recurrence) && (
            <div className="task-detail-modal-panel">
              <div className="task-detail-modal-panel-header">
                <span>Lặp lại</span>
                <button
                  type="button"
                  className="modal-close"
                  onClick={() => setShowRecurrence(false)}
                  aria-label="Đóng"
                >
                  <X size={13} />
                </button>
              </div>
              <RecurrenceConfig value={recurrence} onChange={setRecurrence} />
            </div>
          )}

          {(showReminders || reminders.length > 0) && (
            <div className="task-detail-modal-panel">
              <div className="task-detail-modal-panel-header">
                <span>Nhắc nhở</span>
                <button
                  type="button"
                  className="modal-close"
                  onClick={() => setShowReminders(false)}
                  aria-label="Đóng"
                >
                  <X size={13} />
                </button>
              </div>
              <ReminderConfigComponent value={reminders} onChange={setReminders} />
            </div>
          )}
        </div>
      )}
    </form>
  )
}
