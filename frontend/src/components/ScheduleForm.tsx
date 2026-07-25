import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Layers, MapPin, Calendar, TextQuote, MoveRight, RefreshCw, Bell, Paperclip, X } from 'lucide-react'

import type { Schedule, ScheduleType, RecurrenceRule, ReminderConfig } from '../types'
import { RecurrenceConfig } from './RecurrenceConfig'
import { ReminderConfig as ReminderConfigComponent } from './ReminderConfig'
import { MarkdownField } from './MarkdownField'

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

interface ScheduleFormProps {
  onCreate: (schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>) => Promise<void>
  /** If provided (e.g. from a calendar slot click), pre-fills start/end times */
  initialTimes?: { startDate: string; endDate: string } | null
  onClose?: () => void
}

export function ScheduleForm({ onCreate, initialTimes, onClose }: ScheduleFormProps) {
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
      setFormError('Title is required')
      return
    }

    if (!startTime || !endTime) {
      setFormError('Start and end times are required')
      return
    }

    try {
      await onCreate({
        title: title.trim(),
        type,
        start_time: new Date(startTime).toISOString(),
        end_time: new Date(endTime).toISOString(),
        location: location.trim() || null,
        description: description.trim() || null,
        recurrence,
        reminders,
      })
      onClose?.()
    } catch {
      setFormError('Failed to create schedule')
    }
  }

  return (
    <form id="create-event-form" onSubmit={handleSubmit} className="schedule-form">
      {formError && (
        <div className="form-error">{formError}</div>
      )}

      <div className="title-group">
        <input
          type="text"
          className="input-title"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Tên sự kiện của bạn..."
          autoFocus
          required
        />
        <div className="title-underline" />
      </div>

      <div className="grid-row">
        <div className="form-item">
          <label><Layers size={14} /> Phân loại</label>
          <select
            className="input-field"
            value={type}
            onChange={e => setType(e.target.value as ScheduleType)}
          >
            <option value="CLASS">Lớp học (Class)</option>
            <option value="EXAM">Hội chẩn (Exam)</option>
            <option value="PERSONAL">Cá nhân (Personal)</option>
            <option value="DEADLINE">Deadline</option>
            <option value="CRON_EVENT">Cron</option>
          </select>
        </div>
        <div className="form-item">
          <label><MapPin size={14} /> Địa điểm</label>
          <input
            type="text"
            className="input-field"
            value={location}
            onChange={e => setLocation(e.target.value)}
            placeholder="Phòng hoặc Link Zoom"
          />
        </div>
      </div>

      <label><Calendar size={14} /> Thời gian diễn ra</label>
      <div className="time-box">
        <div className="time-segment">
          <div className="time-segment-label">BẮT ĐẦU</div>
          <input
            type="datetime-local"
            value={startTime}
            onChange={e => setStartTime(e.target.value)}
            required
          />
        </div>
        <div className="time-arrow">
          <MoveRight size={20} />
        </div>
        <div className="time-segment">
          <div className="time-segment-label">KẾT THÚC</div>
          <input
            type="datetime-local"
            value={endTime}
            onChange={e => setEndTime(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="form-item">
        <label><TextQuote size={14} /> Ghi chú thêm</label>
        <MarkdownField
          className="input-field"
          rows={2}
          value={description}
          onChange={setDescription}
          placeholder="Nội dung tóm tắt..."
          ariaLabel="Ghi chú thêm (markdown)"
        />
      </div>

      <div className="options-group">
        <button
          type="button"
          className={`pill ${recurrence ? 'active' : ''}`}
          onClick={() => setShowRecurrence(s => !s)}
        >
          <RefreshCw size={14} /> Lặp lại
        </button>
        <button
          type="button"
          className={`pill ${reminders.length > 0 ? 'active' : ''}`}
          onClick={() => setShowReminders(s => !s)}
        >
          <Bell size={14} /> Nhắc nhở
        </button>
        <button type="button" className="pill" disabled title="Sắp ra mắt">
          <Paperclip size={14} /> Đính kèm
        </button>
      </div>

      {(showRecurrence || recurrence) && (
        <div className="options-panel">
          {showRecurrence ? (
            <div className="options-panel-header">
              <span>Lặp lại</span>
              <button
                type="button"
                className="options-panel-close"
                onClick={() => setShowRecurrence(false)}
                aria-label="Đóng"
              >
                <X size={14} />
              </button>
            </div>
          ) : null}
          <RecurrenceConfig value={recurrence} onChange={setRecurrence} />
        </div>
      )}

      {(showReminders || reminders.length > 0) && (
        <div className="options-panel">
          {showReminders ? (
            <div className="options-panel-header">
              <span>Nhắc nhở</span>
              <button
                type="button"
                className="options-panel-close"
                onClick={() => setShowReminders(false)}
                aria-label="Đóng"
              >
                <X size={14} />
              </button>
            </div>
          ) : null}
          <ReminderConfigComponent value={reminders} onChange={setReminders} />
        </div>
      )}
    </form>
  )
}
