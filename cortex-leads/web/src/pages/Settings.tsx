import { useSearchParams } from 'react-router-dom'
import { PageHeader, Tabs } from '../components/ui'
import { GoogleSection } from './Google'
import { SettingsAi } from './SettingsAi'
import { SettingsBusiness } from './SettingsBusiness'
import { SettingsChannels } from './SettingsChannels'
import { SettingsNotify } from './SettingsNotify'

const TABS = [{ id: 'business', label: 'Doanh nghiệp' }, { id: 'channels', label: 'Kênh nhắn tin' }, { id: 'notify', label: 'Thông báo' }, { id: 'ai', label: 'AI' }, { id: 'google', label: 'Kết nối Google' }] as const
type Tab = (typeof TABS)[number]['id']

export function Settings() {
  const [q, setQ] = useSearchParams()
  const asked = q.get('tab')
  // Google sends the person back here with ?connected= or ?error= and no tab: that is the Google tab.
  const tab: Tab = TABS.find((t) => t.id === asked)?.id ?? (q.get('connected') || q.get('error') ? 'google' : 'business')
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-8">
      <PageHeader title="Cài đặt" subtitle="Hồ sơ doanh nghiệp, kênh nhắn tin, nơi nhận thông báo và giới hạn của AI." />
      <Tabs tabs={[...TABS]} value={tab} onChange={(id) => setQ({ tab: id }, { replace: true })} />
      {tab === 'business' && <SettingsBusiness />}
      {tab === 'channels' && <SettingsChannels />}
      {tab === 'notify' && <SettingsNotify />}
      {tab === 'ai' && <SettingsAi />}
      {tab === 'google' && <GoogleSection />}
    </div>
  )
}
