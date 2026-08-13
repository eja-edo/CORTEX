import { type ChangeEvent } from 'react'
import { KeyValueTable } from './KeyValueTable'

const METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'] as const
const AUTH_TYPES = [
  { value: 'none', label: 'None' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'apikey', label: 'API Key' },
] as const

type AuthConfig = {
  type?: string
  token?: string
  username?: string
  password?: string
  key?: string
  value?: string
  add_to?: string
}

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function CallApiConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }
  const params = (config.params as Record<string, string>) ?? {}
  const headers = (config.headers as Record<string, string>) ?? {}
  const auth = (config.auth as AuthConfig) ?? { type: 'none' }

  const setParams = (value: Record<string, string>) => onChange({ ...config, params: value })
  const setHeaders = (value: Record<string, string>) => onChange({ ...config, headers: value })
  const setAuth = (patch: Partial<AuthConfig>) => onChange({ ...config, auth: { ...auth, ...patch } })

  return (
    <div className="wf-config-fields">
      <div className="wf-config-row">
        <div className="wf-config-field" style={{ flex: 0.3 }}>
          <label className="wf-config-label">Method</label>
          <select
            className="wf-config-select"
            value={(config.method as string) ?? 'GET'}
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
            placeholder="https://api.example.com/resource"
            value={(config.url as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => set('url', e.target.value)}
          />
        </div>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Params</label>
        <KeyValueTable value={params} onChange={setParams} keyPlaceholder="key" valuePlaceholder="value" addLabel="Add param" />
        <span className="wf-config-hint">Được nối vào URL dưới dạng query string. Hỗ trợ template variables.</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Authorization</label>
        <select
          className="wf-config-select"
          value={auth.type ?? 'none'}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => setAuth({ type: e.target.value })}
        >
          {AUTH_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
        {auth.type === 'bearer' && (
          <input
            type="text"
            className="wf-config-input"
            placeholder="{{trigger.token}}"
            value={auth.token ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => setAuth({ token: e.target.value })}
            style={{ marginTop: 6 }}
          />
        )}
        {auth.type === 'basic' && (
          <div className="wf-config-row" style={{ marginTop: 6 }}>
            <input
              type="text"
              className="wf-config-input"
              placeholder="Username"
              value={auth.username ?? ''}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAuth({ username: e.target.value })}
            />
            <input
              type="text"
              className="wf-config-input"
              placeholder="Password"
              value={auth.password ?? ''}
              onChange={(e: ChangeEvent<HTMLInputElement>) => setAuth({ password: e.target.value })}
            />
          </div>
        )}
        {auth.type === 'apikey' && (
          <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div className="wf-config-row">
              <input
                type="text"
                className="wf-config-input"
                placeholder="Key (e.g. X-API-Key)"
                value={auth.key ?? ''}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setAuth({ key: e.target.value })}
              />
              <input
                type="text"
                className="wf-config-input"
                placeholder="Value"
                value={auth.value ?? ''}
                onChange={(e: ChangeEvent<HTMLInputElement>) => setAuth({ value: e.target.value })}
              />
            </div>
            <select
              className="wf-config-select"
              value={auth.add_to ?? 'header'}
              onChange={(e: ChangeEvent<HTMLSelectElement>) => setAuth({ add_to: e.target.value })}
            >
              <option value="header">Add to Header</option>
              <option value="query">Add to Query Params</option>
            </select>
          </div>
        )}
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Headers</label>
        <KeyValueTable value={headers} onChange={setHeaders} keyPlaceholder="Header name" valuePlaceholder="Value" addLabel="Add header" />
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Body</label>
        <textarea
          className="wf-config-textarea"
          rows={4}
          placeholder='{"message": "{{trigger.body}}"} — bỏ trống nếu method là GET'
          value={(config.body as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('body', e.target.value)}
        />
        <span className="wf-config-hint">
          Chuỗi thô (không parse JSON ở đây) — khớp đúng kiểu string mà action.call_api nhận. Hỗ trợ template variables.
        </span>
      </div>
      <div className="wf-config-field">
        <span className="wf-config-hint">
          Response sẽ tự parse theo Content-Type: JSON → object, XML → dict lồng nhau, HTML/text → giữ nguyên chuỗi. Xem ở {'{{steps.<label>.body}}'}.
        </span>
      </div>
    </div>
  )
}
