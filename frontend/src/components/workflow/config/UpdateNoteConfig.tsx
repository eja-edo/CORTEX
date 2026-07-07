import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function UpdateNoteConfig({ config, onChange }: Props) {
  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Note ID</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder="e.g. {{trigger.note_id}}"
          value={(config.note_id as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('note_id', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Content</label>
        <textarea
          className="wf-config-textarea"
          rows={4}
          placeholder="Updated content with {{trigger.title}}"
          value={(config.content as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('content', e.target.value)}
        />
        <span className="wf-config-hint">Markdown supported, supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">
          <input
            type="checkbox"
            checked={(config.append as boolean) ?? false}
            onChange={(e: ChangeEvent<HTMLInputElement>) => onChange({ ...config, append: e.target.checked })}
          />
          {' '}Append to existing content
        </label>
      </div>
    </div>
  )
}
