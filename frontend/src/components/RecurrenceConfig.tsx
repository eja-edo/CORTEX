import { useState } from 'react'
import { Repeat, CalendarDays } from 'lucide-react'
import type { RecurrenceRule, RecurrenceFreq } from '../types'

interface RecurrenceConfigProps {
  value: RecurrenceRule | null
  onChange: (rule: RecurrenceRule | null) => void
}


export function RecurrenceConfig({ value, onChange }: RecurrenceConfigProps) {
  const [isEnabled, setIsEnabled] = useState(value !== null && value.freq !== 'NONE')

  const handleToggle = (checked: boolean) => {
    setIsEnabled(checked)
    if (!checked) {
      onChange(null)
    } else {
      onChange({
        freq: 'WEEKLY',
        interval: 1,  // Always 1 - no custom interval
        tzid: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Ho_Chi_Minh',
      })
    }
  }

  const handleFreqChange = (freq: RecurrenceFreq) => {
    if (!value) return
    onChange({ ...value, freq, interval: 1 })  // Always interval 1
  }

  if (!isEnabled) {
    return (
      <div className="form-field">
        <label className="form-label">
          <Repeat size={16} />
          <span style={{ marginLeft: 6 }}>Recurrence</span>
        </label>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => handleToggle(true)}
          style={{ width: '100%', justifyContent: 'flex-start' }}
        >
          <CalendarDays size={14} />
          <span>Set recurrence (weekly, monthly...)</span>
        </button>
      </div>
    )
  }

  return (
    <div className="recurrence-card">
  <div className="recurrence-header">
    <label className="recurrence-title">
      <Repeat size={16} />
      <span>Recurrence</span>
    </label>
    <button
      type="button"
      className="recurrence-remove"
      onClick={() => handleToggle(false)}
    >
      Remove
    </button>
  </div>

  {/* Frequency */}
  <div className="recurrence-group">
    <label>Repeats</label>
    <select
      value={value?.freq || 'WEEKLY'}
      onChange={(e) => handleFreqChange(e.target.value as RecurrenceFreq)}
    >
      <option value="DAILY">Daily</option>
      <option value="WEEKLY">Weekly</option>
      <option value="MONTHLY">Monthly</option>
    </select>
  </div>

  {/* End date */}
  <div className="recurrence-group">
    <label>Ends</label>
    <input
      type="date"
      value={value?.until ? new Date(value.until).toISOString().split('T')[0] : ''}
      onChange={(e) => {
        const date = e.target.value
        const until = date ? new Date(date).toISOString() : undefined
        if (!value) return
        onChange({ ...value, until })
      }}
    />
    <span className="recurrence-hint">
      Leave empty for no end date
    </span>
  </div>

  <div className="recurrence-info">
    {value?.freq === 'WEEKLY' && '📅 Repeats on the same weekday'}
    {value?.freq === 'MONTHLY' && '📅 Repeats on the same date each month'}
    {value?.freq === 'DAILY' && '📅 Repeats every day'}
  </div>
</div>
  )
}

