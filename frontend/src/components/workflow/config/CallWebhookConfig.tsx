import { type ChangeEvent } from 'react'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function CallWebhookConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }
  const setJson = (key: string, value: string) => {
    if (!value) {
      const rest = { ...config }
      delete rest[key]
      onChange(rest)
    } else {
      try {
        JSON.parse(value)
        onChange({ ...config, [key]: JSON.parse(value) })
      } catch {
        // allow typing
      }
    }
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-row">
        <div className="wf-config-field" style={{ flex: 0.3 }}>
          <label className="wf-config-label">Method</label>
          <select
            className="wf-config-select"
            value={(config.method as string) ?? 'POST'}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => set('method', e.target.value)}
          >
            {METHODS.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="wf-config-field" style={{ flex: 0.7 }}>
          <label className="wf-config-label">URL</label>
          <input
            type="text"
            className="wf-config-input"
            placeholder="https://example.com/webhook"
            value={(config.url as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => set('url', e.target.value)}
          />
        </div>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Headers (JSON)</label>
        <textarea
          className="wf-config-textarea"
          rows={2}
          placeholder='{"Authorization": "Bearer {{trigger.token}}"}'
          value={config.headers ? JSON.stringify(config.headers, null, 2) : ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setJson('headers', e.target.value)}
        />
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Body (JSON)</label>
        <textarea
          className="wf-config-textarea"
          rows={4}
          placeholder='{"message": "{{trigger.body}}"}'
          value={config.body ? JSON.stringify(config.body, null, 2) : ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setJson('body', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
    </div>
  )
}