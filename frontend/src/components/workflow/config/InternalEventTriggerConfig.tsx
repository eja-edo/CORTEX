import { useEffect, useState, type ChangeEvent } from 'react'
import { KeyValueTable } from './KeyValueTable'
import { workflowRequest } from '../../../hooks/useWorkflows'
import type { TriggerCatalogEntry } from '../../../types'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function InternalEventTriggerConfig({ config, onChange }: Props) {
  const event = (config.event as string) ?? ''
  const filters = (config.filters as Record<string, string>) ?? {}

  const [catalog, setCatalog] = useState<TriggerCatalogEntry[]>([])
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    workflowRequest<TriggerCatalogEntry[]>('/v1/actions/triggers/catalog')
      .then((entries) => { if (!cancelled) setCatalog(entries) })
      .catch((error) => console.error('Failed to fetch trigger catalog:', error))
      .finally(() => { if (!cancelled) setIsLoading(false) })
    return () => { cancelled = true }
  }, [])

  const setFilters = (value: Record<string, string>) => onChange({ ...config, filters: value })
  const selected = catalog.find((e) => e.event_type === event)

  return (
    <div className="wf-config-fields">
      <div className="wf-config-field">
        <label className="wf-config-label">Event</label>
        <select
          className="wf-config-select"
          value={event}
          disabled={isLoading}
          onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange({ ...config, event: e.target.value })}
        >
          <option value="" disabled>{isLoading ? 'Đang tải...' : 'Chọn sự kiện...'}</option>
          {catalog.map((e) => (
            <option key={e.event_type} value={e.event_type}>{e.label_vi} ({e.event_type})</option>
          ))}
        </select>
        {selected?.has_direct_backend_delivery && (
          // A3: Cortex already delivers this event directly (see
          // notification_subscribers.py's DIRECT_DELIVERY_HANDLERS) —
          // an action.request_attention node here will duplicate it.
          // find_trigger_conflicts still gates this for real at Activate;
          // this is the earlier heads-up.
          <span className="wf-config-hint wf-config-hint--warning">
            Cortex đã tự xử lý sự kiện này — thêm "Yêu Cầu Chú Ý" ở đây có thể bắn trùng thông báo.
          </span>
        )}
      </div>
      <div className="wf-config-field">
        <label className="wf-config-label">Filters (tuỳ chọn)</label>
        <KeyValueTable value={filters} onChange={setFilters} keyPlaceholder="field" valuePlaceholder="value" addLabel="Add filter" />
        <span className="wf-config-hint">
          Chỉ trigger khi payload sự kiện khớp chính xác các field này. Bỏ trống để nhận mọi sự kiện thuộc loại đã chọn.
        </span>
      </div>
    </div>
  )
}
