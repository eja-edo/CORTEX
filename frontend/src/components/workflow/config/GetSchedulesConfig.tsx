import { useEffect } from 'react'

type Props = {
  config: Record<string, unknown>
  onChange: (config: Record<string, unknown>) => void
}

export function GetSchedulesConfig({ config, onChange }: Props) {
  const timezone = (config.timezone as string) || Intl.DateTimeFormat().resolvedOptions().timeZone

  useEffect(() => {
    if (!config.timezone) {
      onChange({ ...config, timezone })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="wf-config-fields">
      <div className="wf-config-row">
        <div className="wf-config-field">
          <p style={{ color: 'var(--text-secondary)', fontSize: '13px', margin: 0 }}>
            Lấy lịch trình hôm nay · múi giờ: {timezone}
          </p>
        </div>
      </div>
    </div>
  )
}
