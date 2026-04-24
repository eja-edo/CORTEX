import { useState } from 'react'
import { Repeat, CalendarDays } from 'lucide-react'
import type { RecurrenceRule, RecurrenceFreq } from '../types'

interface RecurrenceConfigProps {
  value: RecurrenceRule | null
  onChange: (rule: RecurrenceRule | null) => void
}

const WEEKDAYS = [
  { key: 'MO', label: 'Mon' },
  { key: 'TU', label: 'Tue' },
  { key: 'WE', label: 'Wed' },
  { key: 'TH', label: 'Thu' },
  { key: 'FR', label: 'Fri' },
  { key: 'SA', label: 'Sat' },
  { key: 'SU', label: 'Sun' },
]

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
    <div className="form-field" style={{ padding: '12px', background: 'var(--bg-secondary)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <label className="form-label" style={{ marginBottom: 0 }}>
          <Repeat size={16} />
          <span style={{ marginLeft: 6 }}>Recurrence</span>
        </label>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => handleToggle(false)}
          style={{ fontSize: 12, padding: '4px 8px' }}
        >
          Remove
        </button>
      </div>

      {/* Frequency */}
      <div style={{ marginBottom: 12 }}>
        <label className="form-label" style={{ fontSize: 12 }}>Repeats</label>
        <select
          className="form-select"
          value={value?.freq || 'WEEKLY'}
          onChange={(e) => handleFreqChange(e.target.value as RecurrenceFreq)}
        >
          <option value="DAILY">Daily</option>
          <option value="WEEKLY">Weekly</option>
          <option value="MONTHLY">Monthly</option>
        </select>
      </div>

      {/* Info text */}
      <div style={{ marginBottom: 12, padding: '8px 10px', background: 'var(--bg-tertiary)', borderRadius: 4, fontSize: 12, color: 'var(--text-secondary)' }}>
        {value?.freq === 'WEEKLY' && '📅 Repeats on the same day of week as start time'}
        {value?.freq === 'MONTHLY' && '📅 Repeats on the same day of month as start time'}
        {value?.freq === 'DAILY' && '📅 Repeats every day'}
      </div>

      {/* End date */}
      <div>
        <label className="form-label" style={{ fontSize: 12 }}>Ends</label>
        <input
          type="date"
          className="form-input"
          value={value?.until ? new Date(value.until).toISOString().split('T')[0] : ''}
          onChange={(e) => {
            const date = e.target.value
            const until = date ? new Date(date).toISOString() : undefined
            if (!value) return
            onChange({ ...value, until })
          }}
          style={{ fontSize: 13 }}
        />
        <div style={{ marginTop: 4, fontSize: 11, color: 'var(--text-disabled)' }}>
          Leave empty for no end date
        </div>
      </div>
    </div>
  )
}

// Helper for clsx (simple implementation)
function clsx(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(' ')
}
