import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function WaitConfig({ config, onChange }: Props) {
  return (
    <div className="wf-config-fields">
      <div className="wf-config-row">
        <div className="wf-config-field" style={{ flex: 0.5 }}>
          <label className="wf-config-label">Duration</label>
          <input
            type="number"
            className="wf-config-input"
            min={0}
            placeholder="5"
            value={(config.duration as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange({ ...config, duration: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div className="wf-config-field" style={{ flex: 0.5 }}>
          <label className="wf-config-label">Unit</label>
          <select
            className="wf-config-select"
            value={(config.unit as string) ?? 'minutes'}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange({ ...config, unit: e.target.value })}
          >
            <option value="seconds">Seconds</option>
            <option value="minutes">Minutes</option>
            <option value="hours">Hours</option>
          </select>
        </div>
      </div>
    </div>
  )
}
