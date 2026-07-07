import { type ChangeEvent } from 'react'

const OPERATORS = [
  { value: 'equals', label: 'Equals (==)' },
  { value: 'not_equals', label: 'Not Equals (!=)' },
  { value: 'contains', label: 'Contains' },
  { value: 'greater_than', label: 'Greater Than (>)' },
  { value: 'less_than', label: 'Less Than (<)' },
  { value: 'is_empty', label: 'Is Empty' },
]

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function ConditionConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Variable</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="e.g. {{steps.NODE_ID.result}}"
          value={(config.variable as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('variable', e.target.value)}
        />
        <span className="wf-config-hint">Use template variable syntax</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Operator</label>
        <select
          className="wf-config-select"
          value={(config.operator as string) ?? 'equals'}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => set('operator', e.target.value)}
        >
          {OPERATORS.map(op => (
            <option key={op.value} value={op.value}>{op.label}</option>
          ))}
        </select>
      </div>
      {(config.operator as string) !== 'is_empty' && (
        <div className="wf-config-field">
          <label className="wf-config-label">Value</label>
          <input
            type="text"
            className="wf-config-input"
            placeholder="Value to compare against"
            value={(config.value as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => set('value', e.target.value)}
          />
          <span className="wf-config-hint">Supports template variables</span>
        </div>
      )}
    </div>
  )
}
