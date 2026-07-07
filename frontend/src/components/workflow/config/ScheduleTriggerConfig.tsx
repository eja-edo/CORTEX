import { useState, useCallback, useMemo, useRef, useEffect } from 'react'
import { Clock, Calendar, Repeat, Plus, Trash2, X } from 'lucide-react'
import type { RecurrenceFreq } from '../../../types'

type ScheduleEntry = {
  id: string
  cron: string
  start: string
  freq: RecurrenceFreq
  until: string | null
}

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

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

function entryToCron(start: string, freq: RecurrenceFreq): string {
  const d = new Date(start)
  const min = d.getMinutes()
  const hour = d.getHours()

  if (freq === 'DAILY') return `${min} ${hour} * * *`
  if (freq === 'WEEKLY') return `${min} ${hour} * * ${d.getDay()}`
  if (freq === 'MONTHLY') return `${min} ${hour} ${d.getDate()} * *`
  return `${min} ${hour} * * *`
}

function cronToHuman(cron: string): string {
  const parts = cron.trim().split(/\s+/)
  if (parts.length !== 5) return cron
  const [min, hour, dom, month, dow] = parts
  if (cron === '0 * * * *') return 'Every hour at :00'
  if (cron.match(/^\d+ \* \* \* \*$/)) return `Every hour at :${min}`
  if (dom === '*' && dow === '*' && month === '*') return `Daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (dom === '*' && month === '*') {
    const days: Record<string, string> = { '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat' }
    if (dow in days) return `${days[dow]} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
    if (dow === '1-5') return `Weekdays at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  }
  if (dow === '*' && month === '*' && dom !== '*') return `Monthly (day ${dom}) at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`
  return cron
}

function getNextOccurrences(cron: string, count = 3): Date[] {
  try {
    const parts = cron.trim().split(/\s+/)
    if (parts.length !== 5) return []
    const [cMin, cHour, cDom, cMonth, cDow] = parts
    const now = new Date()
    const results: Date[] = []
    let cur = new Date(now)

    for (let attempts = 0; attempts < 525600 && results.length < count; attempts++) {
      cur = new Date(cur.getTime() + 60000)
      const min = cur.getMinutes()
      const hour = cur.getHours()
      const dom = cur.getDate()
      const month = cur.getMonth() + 1
      const dow = cur.getDay()

      const matches = (pattern: string, val: number): boolean => pattern === '*' || pattern === String(val) || pattern.includes(`${val}`)
      if (matches(cMin, min) && matches(cHour, hour) && matches(cDom, dom) && matches(cMonth, month) && matches(cDow, dow)) {
        results.push(new Date(cur))
      }
    }
    return results
  } catch {
    return []
  }
}

function AddTimeModal({ timezone, initial, onClose, onCreated, onUpdated }: {
  timezone: string
  initial?: ScheduleEntry | null
  onClose: () => void
  onCreated: (entry: ScheduleEntry) => void
  onUpdated: (entry: ScheduleEntry) => void
}) {
  const [startTime, setStartTime] = useState(() => initial ? toLocalInputDateTime(new Date(initial.start)) : toLocalInputDateTime(getNowRounded()))
  const [freq, setFreq] = useState<RecurrenceFreq>(initial?.freq ?? 'DAILY')
  const [until, setUntil] = useState(initial?.until ? new Date(initial.until).toISOString().split('T')[0] : '')
  const [error, setError] = useState<string | null>(null)
  const isEdit = !!initial

  const cron = useMemo(() => {
    if (!startTime) return ''
    return entryToCron(startTime, freq)
  }, [startTime, freq])

  const nextOccurrences = useMemo(() => getNextOccurrences(cron, 3), [cron])

  const backdropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (e.target === backdropRef.current) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const handleSave = useCallback(() => {
    if (!startTime) { setError('Time is required'); return }
    if (!cron) { setError('Invalid time'); return }

    const entry: ScheduleEntry = {
      id: initial?.id ?? crypto.randomUUID(),
      cron,
      start: new Date(startTime).toISOString(),
      freq,
      until: until ? new Date(until).toISOString() : null,
    }
    if (isEdit) onUpdated(entry)
    else onCreated(entry)
    onClose()
  }, [startTime, cron, freq, until, initial, isEdit, onCreated, onUpdated, onClose])

  return (
    <div className="wf-modal-backdrop" ref={backdropRef}>
      <div className="wf-modal">
        <div className="wf-modal-header">
          <div className="wf-modal-header-left">
            <div className="wf-modal-title">{isEdit ? 'Edit Schedule Time' : 'Add Schedule Time'}</div>
            <div className="wf-modal-subtitle">Set when this workflow should run</div>
          </div>
          <button type="button" className="wf-modal-close" onClick={onClose}>
            <X size={18} />
          </button>
        </div>

        <div className="wf-modal-body">
          {error && <div className="wf-modal-error">{error}</div>}

          <div className="wf-modal-field">
            <label className="wf-modal-label">Time</label>
            <input
              type="datetime-local"
              className="wf-modal-input"
              value={startTime}
              onChange={e => setStartTime(e.target.value)}
            />
          </div>

          <div className="wf-modal-field">
            <label className="wf-modal-label">Repeat</label>
            <select
              className="wf-modal-select"
              value={freq}
              onChange={e => setFreq(e.target.value as RecurrenceFreq)}
            >
              <option value="DAILY">Daily</option>
              <option value="WEEKLY">Weekly (same weekday)</option>
              <option value="MONTHLY">Monthly (same date)</option>
            </select>
          </div>

          <div className="wf-modal-field">
            <label className="wf-modal-label">End Date (optional)</label>
            <input
              type="date"
              className="wf-modal-input"
              value={until}
              onChange={e => setUntil(e.target.value)}
            />
          </div>

          <div className="wf-modal-divider" />

          <div className="wf-modal-field">
            <label className="wf-modal-label">Preview</label>
            <div className="wf-modal-cron-preview">
              <span className="wf-modal-cron-human">{cronToHuman(cron)}</span>
            </div>
          </div>

          {nextOccurrences.length > 0 && (
            <div className="wf-modal-field">
              <label className="wf-modal-label">Next Runs</label>
              <div className="wf-modal-occurrences">
                {nextOccurrences.map((d, i) => (
                  <div key={i} className="wf-modal-occurrence">
                    <Clock size={12} />
                    <span>{d.toLocaleDateString()} {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="wf-modal-footer">
          <button type="button" className="wf-modal-btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="wf-modal-btn-primary"
            onClick={handleSave}
            disabled={!cron}
          >
            <Plus size={14} />
            {isEdit ? 'Save' : 'Add Time'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function ScheduleTriggerConfig({ config, onChange }: Props) {
  const [editingEntry, setEditingEntry] = useState<ScheduleEntry | null>(null)

  const schedules = useMemo<ScheduleEntry[]>(() => {
    if (Array.isArray(config.schedules)) {
      return config.schedules as ScheduleEntry[]
    }
    if (config.cron) {
      return [{
        id: crypto.randomUUID(),
        cron: config.cron as string,
        start: (config.schedule_start as string) || new Date().toISOString(),
        freq: (config.schedule_freq as RecurrenceFreq) || 'DAILY',
        until: null,
      }]
    }
    return []
  }, [config])

  const timezone = (config.timezone as string) || Intl.DateTimeFormat().resolvedOptions().timeZone

  const handleAdd = useCallback((entry: ScheduleEntry) => {
    onChange({ ...config, schedules: [...schedules, entry], timezone })
  }, [schedules, config, onChange, timezone])

  const handleUpdate = useCallback((entry: ScheduleEntry) => {
    onChange({ ...config, schedules: schedules.map(s => s.id === entry.id ? entry : s), timezone })
  }, [schedules, config, onChange, timezone])

  const handleRemove = useCallback((id: string) => {
    onChange({ ...config, schedules: schedules.filter(s => s.id !== id), timezone })
  }, [schedules, config, onChange, timezone])

  const allNextOccurrences = useMemo(() => {
    const all: Date[] = []
    for (const entry of schedules) {
      const next = getNextOccurrences(entry.cron, 2)
      all.push(...next)
    }
    return all.sort((a, b) => a.getTime() - b.getTime()).slice(0, 5)
  }, [schedules])

  return (
    <div className="wf-config-fields">
      {schedules.length > 0 ? (
        <div className="wf-config-field">
          <label className="wf-config-label">Schedule Times</label>
          <div className="wf-config-schedule-list">
            {schedules.map((entry) => (
              <div
                key={entry.id}
                className="wf-config-schedule-item"
                role="button"
                tabIndex={0}
                onClick={() => setEditingEntry(entry)}
                onKeyDown={e => e.key === 'Enter' && setEditingEntry(entry)}
                title="Click to edit"
              >
                <div style={{ flex: 1 }}>
                  <div className="wf-config-schedule-title">
                    <Repeat size={12} style={{ display: 'inline', marginRight: 4 }} />
                    {cronToHuman(entry.cron)}
                  </div>
                  <div className="wf-config-schedule-time">
                    {freqLabel(entry.freq)} &middot; {timezone}
                  </div>
                </div>
                <button
                  type="button"
                  className="wf-config-remove-btn"
                  onClick={e => { e.stopPropagation(); handleRemove(entry.id) }}
                  title="Remove"
                >
                  <Trash2 size={13} />
                </button>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="wf-config-field">
          <label className="wf-config-label">Schedule</label>
          <p className="wf-config-desc">
            No schedule times configured. Add one or more times for this workflow to run automatically.
          </p>
        </div>
      )}

      <button type="button" className="wf-config-open-modal-btn" onClick={() => setEditingEntry({ id: '', cron: '', start: '', freq: 'DAILY', until: null })}>
        <Plus size={14} />
        Add time
      </button>

      {allNextOccurrences.length > 0 && (
        <div className="wf-config-field">
          <label className="wf-config-label">Next Runs</label>
          <div className="wf-config-occurrences">
            {allNextOccurrences.map((d, i) => (
              <div key={i} className="wf-config-occurrence">
                <Clock size={12} />
                <span>{d.toLocaleDateString()} {d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {editingEntry !== null && (
        <AddTimeModal
          timezone={timezone}
          initial={editingEntry.id ? editingEntry : null}
          onClose={() => setEditingEntry(null)}
          onCreated={handleAdd}
          onUpdated={handleUpdate}
        />
      )}
    </div>
  )
}

function freqLabel(freq: string): string {
  if (freq === 'DAILY') return 'Daily'
  if (freq === 'WEEKLY') return 'Weekly'
  if (freq === 'MONTHLY') return 'Monthly'
  return freq
}
