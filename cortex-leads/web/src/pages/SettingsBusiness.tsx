import { useEffect, useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useBusiness, useSaveBusiness } from '../api/hooks'
import { Button, Card, ErrorBox, Loading, Notice } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const ZONES = ['Asia/Ho_Chi_Minh', 'Asia/Bangkok', 'Asia/Singapore', 'Asia/Manila', 'Asia/Tokyo', 'Australia/Sydney', 'Europe/Paris', 'UTC']

/** The line a customer reads. Mirrors the server's `ai_disclosure`; the server's own answer replaces it after a save. */
const preview = (name: string, ai: string) => (ai.trim() ? `Trợ lý AI ${ai.trim()} của ${name.trim()}` : `Trợ lý AI của ${name.trim()}`)

export function SettingsBusiness() {
  const q = useBusiness()
  const save = useSaveBusiness()
  const [f, setF] = useState({ name: '', timezone: 'Asia/Ho_Chi_Minh', start: '08:00', end: '21:00', ai_name: '' })
  useEffect(() => { if (q.data) setF({ name: q.data.name, timezone: q.data.timezone, start: q.data.hours.start, end: q.data.hours.end, ai_name: q.data.ai_name ?? '' }) }, [q.data])
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const zones = ZONES.includes(f.timezone) ? ZONES : [f.timezone, ...ZONES]
  const wrongOrder = f.end <= f.start
  const submit = (e: FormEvent) => { e.preventDefault(); save.mutate({ name: f.name, timezone: f.timezone, hours: { start: f.start, end: f.end }, ai_name: f.ai_name.trim() || null }) }
  return (
    <Card className="max-w-2xl p-6">
      <form onSubmit={submit} className="flex flex-col gap-4">
        <h2 className="text-[15px] font-bold">Hồ sơ doanh nghiệp</h2>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên doanh nghiệp
          <input className={input} value={f.name} maxLength={80} onChange={(e) => setF({ ...f, name: e.target.value })} /></label>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Múi giờ
          <select className={input} value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })}>{zones.map((z) => <option key={z}>{z}</option>)}</select>
          <span className="text-xs font-normal text-ink-3">Mọi giờ trên màn hình và giờ AI được nhắn khách đều theo múi giờ này.</span></label>
        <fieldset className="flex flex-col gap-1.5"><legend className="mb-1.5 text-[13px] font-semibold">Giờ làm việc</legend>
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-[13px]">Mở cửa<input type="time" aria-label="Giờ mở cửa" className={input} value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></label>
            <label className="flex items-center gap-2 text-[13px]">Đóng cửa<input type="time" aria-label="Giờ đóng cửa" className={input} value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></label>
          </div>
          <span className="text-xs text-ink-3">Ngoài giờ này AI không tự nhắn khách: tin chờ tới giờ mở cửa kế tiếp.</span>
          {wrongOrder && <span role="alert" className="text-[13px] text-bad">Giờ đóng cửa phải sau giờ mở cửa.</span>}
          {q.data.hours_differ && <Notice tone="warn">Các sandbox đang có giờ khác nhau. Lưu ở đây sẽ đặt cùng một giờ cho tất cả.</Notice>}
        </fieldset>
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên của trợ lý AI (không bắt buộc)
          <input className={input} value={f.ai_name} maxLength={40} placeholder="Mai" onChange={(e) => setF({ ...f, ai_name: e.target.value })} />
          <span className="text-xs font-normal text-ink-3">Khách luôn được báo đây là AI. Dòng khách đọc: <b data-testid="disclosure" className="text-ink">{preview(f.name || '…', f.ai_name)}</b></span></label>
        {save.isError && <p role="alert" className="text-[13px] text-bad">{explain(save.error)}</p>}
        {save.isSuccess && <Notice tone="ok">Đã lưu.</Notice>}
        <div><Button variant="primary" type="submit" busy={save.isPending} disabled={f.name.trim().length < 2 || wrongOrder}>Lưu thay đổi</Button></div>
      </form>
    </Card>
  )
}
