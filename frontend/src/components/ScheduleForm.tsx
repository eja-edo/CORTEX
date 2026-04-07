import { useState } from 'react'
import type { FormEvent } from 'react'
import { LayoutDashboard, Plus } from 'lucide-react'
import type { Schedule, ScheduleType } from '../types'

function toLocalInputDateTime(value: Date): string {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60000)
  return local.toISOString().slice(0, 16)
}

interface ScheduleFormProps {
  onCreate: (schedule: Omit<Schedule, 'id' | 'user_id' | 'created_at' | 'updated_at' | 'is_completed'>) => Promise<void>
  weekRange: { startDate: string; endDate: string }
}

export function ScheduleForm({ onCreate, weekRange }: ScheduleFormProps) {
  const [title, setTitle] = useState<string>('')
  const [type, setType] = useState<ScheduleType>('CLASS')
  const [startTime, setStartTime] = useState<string>(weekRange.startDate)
  const [endTime, setEndTime] = useState<string>(() => {
    const start = new Date(weekRange.startDate)
    start.setHours(start.getHours() + 1)
    return toLocalInputDateTime(start)
  })
  const [location, setLocation] = useState<string>('')
  const [description, setDescription] = useState<string>('')
  const [formError, setFormError] = useState<string>('')

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
    if (end <= start) {
      setFormError('End time must be later than start time.')
      return
    }

    setFormError('')
    await onCreate({
      title,
      type,
      start_time: start.toISOString(),
      end_time: end.toISOString(),
      location: location || null,
      description: description || null,
    })
    setTitle('')
    setLocation('')
    setDescription('')
  }

  return (
    <article className="panel">
      <div className="schedule-toolbar" style={{ marginBottom: '1rem' }}>
        <h2>
          <LayoutDashboard size={20} style={{ display: 'inline', verticalAlign: 'text-bottom', marginRight: '6px' }} /> New Event
        </h2>
      </div>
      <form className="form-grid" onSubmit={handleSubmit}>
        {formError ? <p className="status error">{formError}</p> : null}
        <label>
          Title
          <input value={title} required placeholder="e.g. Advanced Calculus" onChange={(e) => setTitle(e.target.value)} />
        </label>

        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value as ScheduleType)}>
            <option value="CLASS">Class</option>
            <option value="DEADLINE">Deadline</option>
            <option value="EXAM">Exam</option>
            <option value="PERSONAL">Personal</option>
          </select>
        </label>

        <label>
          Start Time
          <input type="datetime-local" required value={startTime} onChange={(e) => handleStartTimeChange(e.target.value)} />
        </label>

        <label>
          End Time
          <input type="datetime-local" required value={endTime} onChange={(e) => setEndTime(e.target.value)} />
        </label>

        <label>
          Location (optional)
          <input value={location} placeholder="e.g. Room 302" onChange={(e) => setLocation(e.target.value)} />
        </label>

        <label>
          Notes (optional)
          <textarea value={description} placeholder="Preparation materials..." rows={3} onChange={(e) => setDescription(e.target.value)} />
        </label>

        <button className="primary" type="submit" style={{ marginTop: '0.5rem' }}>
          <Plus size={18} /> Add to Schedule
        </button>
      </form>
    </article>
  )
}
