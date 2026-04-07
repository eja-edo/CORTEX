import { useState } from 'react'
import type { FormEvent } from 'react'
import { Plus } from 'lucide-react'
import type { Schedule, ScheduleType } from '../types'

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

interface ScheduleFormProps {
  onCreate: (schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>) => Promise<void>
  weekRange: { startDate: string; endDate: string }
  onClose?: () => void
}

export function ScheduleForm({ onCreate, weekRange, onClose }: ScheduleFormProps) {
  const [title, setTitle] = useState('')
  const [type, setType] = useState<ScheduleType>('CLASS')
  const [startTime, setStartTime] = useState(weekRange.startDate)
  const [endTime, setEndTime] = useState(() => {
    const start = new Date(weekRange.startDate)
    start.setHours(start.getHours() + 1)
    return toLocalInputDateTime(start)
  })
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState('')

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
    await onCreate({ title, type, start_time: start.toISOString(), end_time: end.toISOString(), location: location || null, description: description || null })
    setTitle(''); setLocation(''); setDescription('')
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