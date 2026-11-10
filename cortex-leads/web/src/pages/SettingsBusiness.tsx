import { useEffect, useState, type FormEvent } from 'react'
import { Bot } from 'lucide-react'
import { explain } from '../api/client'
import { useBusiness, useSaveBusiness } from '../api/hooks'
import { SCard, SFoot, SHead, SRow, fieldCls } from '../components/settingsUi'
import { Button, ErrorBox, Loading, Notice } from '../components/ui'

const ZONES = ['Asia/Ho_Chi_Minh', 'Asia/Bangkok', 'Asia/Singapore', 'Asia/Manila', 'Asia/Tokyo', 'Australia/Sydney', 'Europe/Paris', 'UTC']

/** The line a customer reads. Mirrors the server's `ai_disclosure`; the server's own answer replaces it after a save. */
const preview = (name: string, ai: string) => (ai.trim() ? `Trợ lý AI ${ai.trim()} của ${name.trim()}` : `Trợ lý AI của ${name.trim()}`)
/** 24-hour times typed as text: a native time box shows AM/PM on a machine set to English. "7:30" is read as "07:30". */
const clock = (v: string) => (/^\d:\d\d$/.test(v.trim()) ? `0${v.trim()}` : v.trim())
const validClock = (v: string) => /^([01]\d|2[0-3]):[0-5]\d$/.test(v)

export function SettingsBusiness() {
  const q = useBusiness()
  const save = useSaveBusiness()
  const [f, setF] = useState({ name: '', timezone: 'Asia/Ho_Chi_Minh', start: '08:00', end: '21:00', ai_name: '' })
  useEffect(() => { if (q.data) setF({ name: q.data.name, timezone: q.data.timezone, start: q.data.hours.start, end: q.data.hours.end, ai_name: q.data.ai_name ?? '' }) }, [q.data])
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const zones = ZONES.includes(f.timezone) ? ZONES : [f.timezone, ...ZONES]
  const start = clock(f.start), end = clock(f.end)
  const badClock = !validClock(start) || !validClock(end)
  const wrongOrder = !badClock && end <= start
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate({ name: f.name, timezone: f.timezone, hours: { start, end }, ai_name: f.ai_name.trim() || null }) }
  return (
    <SCard>
      <form onSubmit={submit}>
        <SHead title="Hồ sơ doanh nghiệp" desc="Thông tin này quyết định tên khách thấy và giờ AI được phép nhắn." />
        <SRow label="Tên doanh nghiệp" htmlFor="biz-name" desc="Hiện trên màn hình và trong dòng AI tự giới thiệu.">
          <input id="biz-name" className={fieldCls} value={f.name} maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} /></SRow>
        <SRow label="Múi giờ" htmlFor="biz-tz" desc="Giờ trên màn hình và giờ AI được nhắn đều theo múi giờ này.">
          <select id="biz-tz" className={fieldCls} value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{zones.map((z) => <option key={z}>{z}</option>)}</select></SRow>
        <SRow label="Giờ làm việc" desc="Ngoài giờ này AI không tự nhắn khách: tin chờ tới giờ mở cửa kế tiếp.">
          <div className="flex flex-wrap items-center gap-3">
            <input aria-label="Giờ mở cửa" inputMode="numeric" placeholder="08:00" maxLength={5} className={`${fieldCls} !w-28`} value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />
            <span className="text-[13px] text-ink-2">đến</span>
            <input aria-label="Giờ đóng cửa" inputMode="numeric" placeholder="21:00" maxLength={5} className={`${fieldCls} !w-28`} value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} />
          </div>
          <span className="text-xs text-ink-3">Định dạng 24 giờ, ví dụ 08:00 hoặc 21:30.</span>
          {badClock && <span role="alert" className="text-[13px] text-bad">Nhập giờ dạng 08:00 (từ 00:00 đến 23:59).</span>}
          {wrongOrder && <span role="alert" className="text-[13px] text-bad">Giờ đóng cửa phải sau giờ mở cửa.</span>}
          {q.data.hours_differ && <Notice tone="warn">Các việc của AI đang có giờ khác nhau. Lưu ở đây sẽ đặt cùng một giờ cho tất cả.</Notice>}
        </SRow>
        <SRow label="Tên trợ lý AI" htmlFor="biz-ai" desc="Không bắt buộc. Khách luôn được báo đây là AI.">
          <input id="biz-ai" className={fieldCls} value={f.ai_name} maxLength={40} placeholder="Mai" onChange={(e) => setF({ ...f, ai_name: e.target.value })} />
          <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-lg bg-ai-soft px-3 py-2.5 text-[13px] text-ink-2"><Bot className="size-4 shrink-0 text-ai" aria-hidden />Khách sẽ đọc: <b data-testid="disclosure" className="font-semibold text-ai">{preview(f.name || '…', f.ai_name)}</b></p>
        </SRow>
        <SFoot>
          {save.isError && <span role="alert" className="mr-auto text-[13px] text-bad">{explain(save.error)}</span>}
          {save.isSuccess && <span role="status" className="mr-auto text-[13px] text-ok">Đã lưu.</span>}
          <Button variant="primary" type="submit" busy={save.isPending} disabled={f.name.trim().length < 2 || badClock || wrongOrder}>Lưu thay đổi</Button>
        </SFoot>
      </form>
    </SCard>
  )
}
