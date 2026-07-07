import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function CallAIConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Prompt</label>
        <textarea
          className="wf-config-textarea"
          rows={4}
          placeholder="What do you want the AI to do? e.g. Summarize: {{trigger.title}}"
          value={(config.prompt as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('prompt', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">System Instruction</label>
        <textarea
          className="wf-config-textarea"
          rows={2}
          placeholder="Optional system instruction"
          value={(config.system_instruction as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('system_instruction', e.target.value)}
        />
      </div>
      <div className="wf-config-row">
        <div className="wf-config-field">
          <label className="wf-config-label">Max Tokens</label>
          <input
            type="number"
            className="wf-config-input"
            placeholder="1024"
            value={(config.max_tokens as string) ?? '1024'}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange({ ...config, max_tokens: parseInt(e.target.value) || 1024 })}
          />
        </div>
        <div className="wf-config-field">
          <label className="wf-config-label">Temperature</label>
          <input
            type="number"
            className="wf-config-input"
            min="0"
            max="2"
            step="0.1"
            placeholder="0.7"
            value={(config.temperature as string) ?? '0.7'}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange({ ...config, temperature: parseFloat(e.target.value) || 0.7 })}
          />
        </div>
      </div>
    </div>
  )
}
