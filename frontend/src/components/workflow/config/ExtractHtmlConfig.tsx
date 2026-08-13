import { type ChangeEvent } from 'react'

const EXTRACT_MODES = ['text', 'html', 'attribute', 'dom'] as const

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function ExtractHtmlConfig({ config, onChange }: Props) {
  const set = (key: string, value: string | boolean) => {
    onChange({ ...config, [key]: value })
  }
  const extractMode = (config.extract as string) ?? 'text'

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">HTML</label>
        <textarea
          className="wf-config-textarea"
          rows={3}
          placeholder="{{steps.callApi.body}}"
          value={(config.html as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLTextAreaElement>) => set('html', e.target.value)}
        />
        <span className="wf-config-hint">Chuỗi HTML nguồn, hỗ trợ template variables — thường lấy từ output của action.call_api.</span>
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">CSS Selector</label>
        <input
          type="text"
          className="wf-config-input"
          placeholder=".class-name, #id, table tr td"
          value={(config.selector as string) ?? ''}
          onChange={(e: ChangeEvent<HTMLInputElement>) => set('selector', e.target.value)}
        />
      </div>
      <div className="wf-config-row">
        <div className="wf-config-field">
          <label className="wf-config-label">Extract</label>
          <select
            className="wf-config-select"
            value={extractMode}
            onChange={(e: ChangeEvent<HTMLSelectElement>) => set('extract', e.target.value)}
          >
            {EXTRACT_MODES.map(m => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        {extractMode === 'attribute' && (
          <div className="wf-config-field">
            <label className="wf-config-label">Attribute</label>
            <input
              type="text"
              className="wf-config-input"
              placeholder="href, src..."
              value={(config.attribute as string) ?? ''}
              onChange={(e: ChangeEvent<HTMLInputElement>) => set('attribute', e.target.value)}
            />
          </div>
        )}
      </div>
      {extractMode === 'dom' && (
        <div className="wf-config-field">
          <span className="wf-config-hint">
            Trả về cây JSON đệ quy {'{tag, attributes, text|children}'} của toàn bộ phần tử khớp — không cần biết trước cấu trúc tag bên trong.
          </span>
        </div>
      )}
      <div className="wf-config-field">
        <label className="wf-config-label">
          <input
            type="checkbox"
            checked={(config.multiple as boolean) ?? false}
            onChange={(e: ChangeEvent<HTMLInputElement>) => set('multiple', e.target.checked)}
          />
          {' '}Lấy tất cả phần tử khớp (mảng) thay vì chỉ phần tử đầu tiên
        </label>
      </div>
      <div className="wf-config-field">
        <span className="wf-config-hint">
          Không tìm thấy phần tử khớp selector vẫn trả success (found: false) — không làm workflow fail. Xem kết quả ở {'{{steps.<label>.value}}'}.
        </span>
      </div>
    </div>
  )
}
