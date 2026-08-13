import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function CreateTaskConfig({ config, onChange }: Props) {
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
          placeholder="Task title"
          value={(config.title as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('title', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Description</label>
        <textarea
          className="wf-config-textarea"
          rows={3}
          placeholder="Optional description"
          value={(config.description as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('description', e.target.value)}
        />
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Due Date</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="2025-01-15T09:00:00 or {{trigger.due_date}}"
          value={(config.due_date as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('due_date', e.target.value)}
        />
        <span className="wf-config-hint">ISO 8601 or template variable. Optional</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Priority</label>
        <select
          className="wf-config-select"
          value={(config.priority as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => set('priority', e.target.value)}
        >
          <option value="">None</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>
      </div>
    </div>
  )
}
