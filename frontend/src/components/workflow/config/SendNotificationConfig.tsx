import { type ChangeEvent } from 'react'
import { AutocompleteField } from './AutocompleteField'
import type { ConfigPanelProps } from './index'

export function SendNotificationConfig({ config, onChange, templateVars }: ConfigPanelProps) {
  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Tiêu đề</label>
        <AutocompleteField
          value={(config.title as string) ?? ''}
          onChange={(v) => onChange({ ...config, title: v })}
          variables={templateVars ?? []}
          placeholder="VD: Đã tạo ghi chú mới"
        />
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
        <AutocompleteField
          value={(config.body as string) ?? ''}
          onChange={(v) => onChange({ ...config, body: v })}
          variables={templateVars ?? []}
          placeholder="VD: Ghi chú đã được tạo thành công"
          multiline
        />
        <span className="wf-config-hint">Gõ {'{{'} để chèn biến</span>
      </div>
    </div>
  )
}
