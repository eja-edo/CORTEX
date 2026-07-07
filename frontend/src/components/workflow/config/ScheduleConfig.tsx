import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function ScheduleConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Title</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="Event title"
          value={(config.title as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('title', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Start Time</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="2025-01-15T09:00:00Z or {{trigger.time}}"
          value={(config.start_time as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('start_time', e.target.value)}
        />
        <span className="wf-config-hint">ISO 8601 or template variable</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">End Time</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="2025-01-15T10:00:00Z or {{trigger.time}}"
          value={(config.end_time as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('end_time', e.target.value)}
        />
        <span className="wf-config-hint">ISO 8601 or template variable</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Description</label>
        <textarea
          className="wf-config-textarea"
          rows={2}
          placeholder="Optional description"
          value={(config.description as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('description', e.target.value)}
        />
      </div>
    </div>
  )
}
