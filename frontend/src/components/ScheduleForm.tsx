import { useState, useEffect } from 'react'
import type { FormEvent } from 'react'
import { Plus } from 'lucide-react'
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
    if (!initialTimes) return
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setStartTime(initialTimes.startDate)
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEndTime(initialTimes.endDate)
  }, [initialTimes])

  const handleStartTimeChange = (nextStart: string) => {
    setStartTime(nextStart)
    const start = new Date(nextStart)
    const end = new Date(endTime)
    if (end <= start) {
      const adjusted = new Date(start)
      adjusted.setHours(adjusted.getHours() + 1)
      setEndTime(toLocalInputDateTime(adjusted))
    }
  }

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const start = new Date(startTime)
    const end = new Date(endTime)
    if (end <= start) { setFormError('End time must be after start time.'); return }
    setFormError('')
    
    await onCreate({
      title,
      type,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      location: location || null,
      description: description || null,
      recurrence: recurrence || undefined,
      reminders: reminders.length > 0 ? reminders : undefined,
    })
    
    setTitle('')
    setLocation('')
    setDescription('')
    setRecurrence(null)
    setReminders([])
    onClose?.()
  }

  return (
    <form className="create-form" onSubmit={handleSubmit}>
      {formError && (
        <div style={{ padding: '8px 10px', background: 'var(--red-light)', border: '1px solid rgba(235,87,87,0.2)', borderRadius: 'var(--radius)', fontSize: 13, color: 'var(--red)' }}>
          {formError}
        </div>
      )}

      <div className="form-field">
        <label className="form-label" htmlFor="ev-title">Event title</label>
        <input id="ev-title" className="form-input" required placeholder="e.g. Advanced Calculus" value={title} onChange={(e) => setTitle(e.target.value)} />
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="ev-type">Type</label>
        <select id="ev-type" className="form-select" value={type} onChange={(e) => setType(e.target.value as ScheduleType)}>
          <option value="CLASS">Class</option>
          <option value="DEADLINE">Deadline</option>
          <option value="EXAM">Exam</option>
          <option value="PERSONAL">Personal</option>
        </select>
      </div>

      <div className="create-form-row">
        <div className="form-field">
          <label className="form-label" htmlFor="ev-start">Start</label>
          <input id="ev-start" className="form-input" type="datetime-local" required value={startTime} onChange={(e) => handleStartTimeChange(e.target.value)} />
        </div>
        <div className="form-field">
          <label className="form-label" htmlFor="ev-end">End</label>
          <input id="ev-end" className="form-input" type="datetime-local" required value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </div>
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="ev-location">Location <span style={{ color: 'var(--text-disabled)', fontWeight: 400 }}>(optional)</span></label>
        <input id="ev-location" className="form-input" placeholder="e.g. Room 302" value={location} onChange={(e) => setLocation(e.target.value)} />
      </div>

      <div className="form-field">
        <label className="form-label" htmlFor="ev-notes">Notes <span style={{ color: 'var(--text-disabled)', fontWeight: 400 }}>(optional)</span></label>
        <textarea id="ev-notes" className="form-textarea" placeholder="Preparation materials, links…" rows={3} value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>

      {/* Recurrence Section */}
      <RecurrenceConfig value={recurrence} onChange={setRecurrence} />

      {/* Reminders Section */}
      <ReminderConfigComponent value={reminders} onChange={setReminders} />

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, paddingTop: 4 }}>
        {onClose && (
          <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
        )}
        <button type="submit" className="btn btn-primary">
          <Plus size={14} /> Add event
        </button>
      </div>
    </form>
  )
}