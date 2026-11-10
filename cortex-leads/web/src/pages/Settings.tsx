import { Bell, Building2, MessageCircle, Plug, Sparkles, type LucideIcon } from 'lucide-react'
import clsx from 'clsx'
import { useSearchParams } from 'react-router-dom'
import { PageHeader, useChosenTabInView } from '../components/ui'
import { GoogleSection } from './Google'
import { SettingsAi } from './SettingsAi'
import { SettingsBusiness } from './SettingsBusiness'
import { SettingsChannels } from './SettingsChannels'
import { SettingsNotify } from './SettingsNotify'

const TABS: { id: string; label: string; icon: LucideIcon }[] = [
  { id: 'business', label: 'Doanh nghiệp', icon: Building2 }, { id: 'channels', label: 'Kênh nhắn tin', icon: MessageCircle },
  { id: 'notify', label: 'Thông báo', icon: Bell }, { id: 'ai', label: 'AI', icon: Sparkles }, { id: 'google', label: 'Kết nối Google', icon: Plug },
]

export function Settings() {
  const [q, setQ] = useSearchParams()
  const asked = q.get('tab')
  // Google sends the person back here with ?connected= or ?error= and no tab: that is the Google tab.
  const tab = TABS.find((t) => t.id === asked)?.id ?? (q.get('connected') || q.get('error') ? 'google' : 'business')
  const row = useChosenTabInView<HTMLDivElement>(tab)
  return (
    <div className="flex h-full flex-col gap-6 overflow-y-auto p-4 sm:p-6 lg:p-8 [&>*]:shrink-0">
      <PageHeader title="Cài đặt" subtitle="Hồ sơ doanh nghiệp, kênh nhắn tin, nơi nhận thông báo và giới hạn của AI." />
      <div className="flex flex-col gap-6 lg:flex-row lg:gap-10">
        <div ref={row} role="tablist" aria-orientation="vertical" aria-label="Mục cài đặt" className="relative flex shrink-0 gap-1 overflow-x-auto [scrollbar-width:none] lg:w-52 lg:flex-col">
          {TABS.map((t) => {
            const on = t.id === tab
            return (
              <button key={t.id} role="tab" aria-selected={on} onClick={() => setQ({ tab: t.id }, { replace: true })}
                className={clsx('flex shrink-0 items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm whitespace-nowrap max-lg:min-h-10', on ? 'border-line bg-surface font-semibold' : 'border-transparent font-medium text-ink-2 hover:bg-surface/60')}>
                <t.icon className={clsx('size-4', on ? 'text-accent' : 'text-ink-2')} aria-hidden />{t.label}
              </button>)
          })}
        </div>
        <div className="flex w-full max-w-[760px] min-w-0 flex-col gap-4">
          {tab === 'business' && <SettingsBusiness />}
          {tab === 'channels' && <SettingsChannels />}
          {tab === 'notify' && <SettingsNotify />}
          {tab === 'ai' && <SettingsAi />}
          {tab === 'google' && <GoogleSection />}
        </div>
      </div>
    </div>
  )
}
