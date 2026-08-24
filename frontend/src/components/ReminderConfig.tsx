import { useState } from 'react'
import { Bell, Plus, X, Clock } from 'lucide-react'
import type { ReminderConfig, ReminderMethod } from '../types'
import { useToast } from '../hooks/useToast'

interface ReminderConfigProps {
  value: ReminderConfig[]
  onChange: (reminders: ReminderConfig[]) => void
}

const PRESET_OPTIONS = [
  { label: '5 minutes before', minutes: 5 },
  { label: '10 minutes before', minutes: 10 },
  { label: '15 minutes before', minutes: 15 },
  { label: '30 minutes before', minutes: 30 },
  { label: '1 hour before', minutes: 60 },
  { label: '2 hours before', minutes: 120 },
  { label: '1 day before', minutes: 1440 },
]

export function ReminderConfig({ value, onChange }: ReminderConfigProps) {
  const toast = useToast()
  const [showPresets, setShowPresets] = useState(false)

  const addReminder = (minutes: number, method: ReminderMethod = 'push') => {
    // Check if already exists
    const exists = value.some(r => r.minutes_before === minutes && r.method === method)
    if (exists) return

    if (value.length >= 5) {
      toast.show({ kind: 'info', message: 'Mỗi sự kiện chỉ đặt được tối đa 5 lời nhắc.' })
      return
    }

    onChange([...value, { minutes_before: minutes, method }])
    setShowPresets(false)
  }

  const removeReminder = (index: number) => {
    onChange(value.filter((_, i) => i !== index))
  }

  const formatReminderLabel = (minutes: number): string => {
    if (minutes < 60) return `${minutes} min before`
    if (minutes < 1440) return `${minutes / 60} hour(s) before`
    return `${minutes / 1440} day(s) before`
  }

  return (
    <div className="form-field">
      <label className="form-label">
        <Bell size={16} />
        <span style={{ marginLeft: 6 }}>Reminders</span>
      </label>

      {/* Current reminders */}
      {value.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 8 }}>
          {value.map((reminder, index) => (
            <div
              key={index}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '8px 10px',
                background: 'var(--bg-secondary)',
                borderRadius: 'var(--radius)',
                fontSize: 13,
              }}
            >
              <Clock size={14} style={{ color: 'var(--text-secondary)' }} />
              <span style={{ flex: 1 }}>{formatReminderLabel(reminder.minutes_before)}</span>
              {reminder.method === 'email' && (
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', padding: '2px 6px', background: 'var(--bg-tertiary)', borderRadius: 4 }}>
                  Email
                </span>
              )}
              <button
                type="button"
                onClick={() => removeReminder(index)}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 4,
                  color: 'var(--text-secondary)',
                  display: 'flex',
                  alignItems: 'center',
                }}
              >
                <X size={14} />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Add reminder button */}
      <div style={{ position: 'relative' }}>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={() => setShowPresets(!showPresets)}
          style={{ width: '100%', justifyContent: 'flex-start' }}
        >
          <Plus size={14} />
          <span>Add reminder</span>
        </button>

        {/* Preset dropdown */}
        {showPresets && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              marginTop: 4,
              padding: 8,
              background: 'var(--bg-primary)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
              zIndex: 100,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            {PRESET_OPTIONS.map(preset => {
              const exists = value.some(r => r.minutes_before === preset.minutes)
              return (
                <button
                  key={preset.minutes}
                  type="button"
                  disabled={exists}
                  onClick={() => addReminder(preset.minutes)}
                  style={{
                    padding: '8px 12px',
                    background: exists ? 'var(--bg-secondary)' : 'transparent',
                    border: 'none',
                    borderRadius: 4,
                    cursor: exists ? 'not-allowed' : 'pointer',
                    textAlign: 'left',
                    fontSize: 13,
                    color: exists ? 'var(--text-disabled)' : 'var(--text-primary)',
                    opacity: exists ? 0.6 : 1,
                  }}
                >
                  {preset.label} {exists && '✓'}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {value.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-disabled)' }}>
          {value.length}/5 reminders set
        </div>
      )}
    </div>
  )
}
