import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function UpdateTaskConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Task ID</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="{{trigger.task_id}}"
          value={(config.task_id as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('task_id', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Title</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="Leave empty to keep unchanged"
          value={(config.title as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('title', e.target.value)}
        />
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Status</label>
        <select
          className="wf-config-select"
          value={(config.status as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => set('status', e.target.value)}
        >
          <option value="">Unchanged</option>
          <option value="todo">Todo</option>
          <option value="in_progress">In Progress</option>
          <option value="done">Done</option>
          <option value="cancelled">Cancelled</option>
        </select>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Due Date</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="Leave empty to keep unchanged"
          value={(config.due_date as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('due_date', e.target.value)}
        />
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Priority</label>
        <select
          className="wf-config-select"
          value={(config.priority as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => set('priority', e.target.value)}
        >
          <option value="">Unchanged</option>
          <option value="low">Low</option>
          <option value="medium">Medium</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>
      </div>
    </div>
  )
}
