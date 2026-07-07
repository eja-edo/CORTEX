import { type ChangeEvent, useRef } from 'react'
import { TemplateHelper } from './TemplateHelper'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function SendNotificationConfig({ config, onChange }: Props) {
  const titleRef = useRef<HTMLInputElement>(null)
  const bodyRef = useRef<HTMLTextAreaElement>(null)

  const set = (key: string, value: string) => {
    onChange({ ...config, [key]: value })
  }

  const insertAt = (ref: { current: HTMLInputElement | HTMLTextAreaElement | null }, variable: string) => {
    const el = ref.current
    if (!el) return
    const start = el.selectionStart ?? el.value.length
    const end = el.selectionEnd ?? start
    const newVal = el.value.slice(0, start) + variable + el.value.slice(end)
    onChange({ ...config, [el.name]: newVal })
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + variable.length, start + variable.length)
    })
  }

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Tiêu đề</label>
        <div style={{ display: 'flex', gap: 4 }}>
          <input
            ref={titleRef}
            name="title"
            type="text"
            className="wf-config-input"
            style={{ flex: 1 }}
            placeholder="VD: Đã tạo ghi chú mới"
            value={(config.title as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLInputElement>) => set('title', e.target.value)}
          />
          <TemplateHelper onInsert={(v) => insertAt(titleRef, v)} />
        </div>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Loại</label>
        <select
          className="wf-config-select"
          value={(config.type as string) ?? 'info'}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange({ ...config, type: e.target.value })}
        >
          <option value="info">Info</option>
          <option value="success">Success</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
        </select>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Nội dung</label>
        <div style={{ display: 'flex', gap: 4 }}>
          <textarea
            ref={bodyRef}
            name="body"
            className="wf-config-textarea"
            style={{ flex: 1 }}
            rows={4}
            placeholder={'VD: Ghi chú "{{trigger.title}}" đã được tạo thành công'}
            value={(config.body as string) ?? ''}
            onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('body', e.target.value)}
          />
          <TemplateHelper onInsert={(v) => insertAt(bodyRef, v)} />
        </div>
        <span className="wf-config-hint">Dùng {'{{trigger.field}}'} hoặc {'{{steps.NODE_ID.result}}'} để chèn dữ liệu</span>
      </div>
    </div>
  )
}
