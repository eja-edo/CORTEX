import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'

import type { Schedule, ScheduleType, RecurrenceRule, ReminderConfig } from '../types'
import { RecurrenceConfig } from './RecurrenceConfig'
import { ReminderConfig as ReminderConfigComponent } from './ReminderConfig'

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

function getNowRounded(): Date {
  const now = new Date()
  // Round up to the next 30-min mark for a cleaner default
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
  
  // New fields for recurrence and reminders
  const [recurrence, setRecurrence] = useState<RecurrenceRule | null>(null)
  const [reminders, setReminders] = useState<ReminderConfig[]>([])
  
  const [formError, setFormError] = useState('')

  // When initialTimes changes (e.g. user clicks a different slot and re-opens),
  // update the fields to reflect the new slot.
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
    <form onSubmit={handleSubmit} className="schedule-form">
      {formError && (
        <div className="form-error">{formError}</div>
      )}

      <div className="form-field">
        <label className="form-label" htmlFor="title">Title</label>
        <input
          id="title"
          type="text"
          className="form-input"
          value={title}
          onChange={e => setTitle(e.target.value)}
          placeholder="Event title"
          required
        />
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="type">Type</label>
        <select
          id="type"
          className="form-select"
          value={type}
          onChange={e => setType(e.target.value as ScheduleType)}
        >
          <option value="CLASS">Class</option>
          <option value="DEADLINE">Deadline</option>
          <option value="EXAM">Exam</option>
          <option value="PERSONAL">Personal</option>
        </select>
      </div>

      <div className="form-row">
        <div className="form-field">
          <label className="form-label" htmlFor="startTime">Start</label>
          <input
            id="startTime"
            type="datetime-local"
            className="form-input"
            value={startTime}
            onChange={e => setStartTime(e.target.value)}
            required
          />
        </div>

        <div className="form-field">
          <label className="form-label" htmlFor="endTime">End</label>
          <input
            id="endTime"
            type="datetime-local"
            className="form-input"
            value={endTime}
            onChange={e => setEndTime(e.target.value)}
            required
          />
        </div>
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="location">Location</label>
        <input
          id="location"
          type="text"
          className="form-input"
          value={location}
          onChange={e => setLocation(e.target.value)}
          placeholder="Room, link, or address"
        />
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="description">Description</label>
        <textarea
          id="description"
          className="form-textarea"
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Optional description"
          rows={3}
        />
      </div>

      <RecurrenceConfig value={recurrence} onChange={setRecurrence} />

      <ReminderConfigComponent value={reminders} onChange={setReminders} />

      <div className="form-actions">
        {onClose && (
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
        )}
        <button type="submit" className="btn btn-primary">
          Create event
        </button>
      </div>
    </form>
  )
}