import { type ChangeEvent } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function CreateNoteConfig({ config, onChange }: Props) {
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
          placeholder="Note title"
          value={(config.title as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('title', e.target.value)}
        />
        <span className="wf-config-hint">Supports template variables</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Content</label>
        <textarea
          className="wf-config-textarea"
          rows={4}
          placeholder="Note content with {{trigger.title}}"
          value={(config.content as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('content', e.target.value)}
        />
        <span className="wf-config-hint">Markdown supported, supports template variables</span>
      </div>
    </div>
  )
}
