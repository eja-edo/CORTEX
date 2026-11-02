import { Bell, Plus, Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useAddTarget, useNotifyTargets, useRemoveTarget, useTestTarget } from '../api/hooks'
import type { NotifyTarget } from '../api/types'
import { Badge, Button, Card, ErrorBox, Loading, Notice } from '../components/ui'

const input = 'rounded-lg border border-line px-3 py-2.5 text-sm font-normal'
const KIND = { telegram: 'Telegram', mezon: 'Mezon' } as const

function Row({ t }: { t: NotifyTarget }) {
  const test = useTestTarget()
  const remove = useRemoveTarget()
  const [ask, setAsk] = useState(false)
  const err = test.error ?? remove.error
  return (
    <div role="row" className="flex flex-col gap-2 border-t border-line px-4 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <Badge tone="accent">{KIND[t.kind]}</Badge>
        <span className="min-w-0 flex-1"><b className="block truncate text-sm">{t.label || KIND[t.kind]}</b><span className="block truncate font-mono text-xs text-ink-2">{t.address}</span></span>
        <span className="text-xs text-ink-2">{t.sandbox ? `Chỉ của «${t.sandbox}»` : 'Chung cho cả doanh nghiệp'}</span>
        <Button busy={test.isPending} onClick={() => test.mutate(t.id)}><Send className="size-4" aria-hidden />Gửi thử</Button>
        {ask ? <><span className="text-xs">Bỏ nơi nhận này?</span><Button variant="dangerSolid" busy={remove.isPending} onClick={() => remove.mutate(t.id)}>Bỏ</Button><Button onClick={() => setAsk(false)}>Không</Button></>
          : <Button variant="danger" onClick={() => setAsk(true)}>Bỏ</Button>}
      </div>
      {test.isSuccess && (test.data.ok ? <p role="status" className="text-xs text-ok">Đã gửi. Hãy kiểm tra xem tin thử có tới nơi không.</p> : <p role="alert" className="text-xs text-bad">Không gửi được. Kiểm tra lại mã nhóm hoặc địa chỉ.</p>)}
      {err && <p role="alert" className="text-xs text-bad">{explain(err)}</p>}
    </div>
  )
}

export function SettingsNotify() {
  const q = useNotifyTargets()
  const add = useAddTarget()
  const [f, setF] = useState({ kind: 'telegram' as 'telegram' | 'mezon', address: '', label: '', sandbox_id: '' })
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate({ kind: f.kind, address: f.address.trim(), label: f.label.trim() || undefined, sandbox_id: f.sandbox_id || null }, { onSuccess: () => setF({ ...f, address: '', label: '' }) }) }
  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <Card className="p-5 text-[13px] text-ink-2"><p className="flex items-start gap-2"><Bell className="mt-0.5 size-4 shrink-0" aria-hidden />
        Khi có khách cần người trả lời, hoặc có lịch học thử mới, hệ thống nhắn vào đây. Tin chỉ có <b className="text-ink">số lượng và đường dẫn</b>, không có tên, số điện thoại hay lời của khách.</p></Card>
      {!q.data.telegram_ready && <Notice tone="warn">Máy chủ chưa có mã bot Telegram (<code>CL_TELEGRAM_BOT_TOKEN</code>), nên nơi nhận kiểu Telegram chưa gửi được. Mezon vẫn dùng được.</Notice>}
      <Card className="overflow-hidden">
        {q.data.items.length === 0 ? <p className="p-5 text-center text-[13px] text-ink-3">Chưa có nơi nhận nào. Nhân viên sẽ chỉ thấy khách cần người khi mở hộp thư.</p> : q.data.items.map((t) => <Row key={t.id} t={t} />)}
      </Card>
      <Card className="p-5"><form onSubmit={submit} className="flex flex-col gap-3">
        <h2 className="text-[15px] font-bold">Thêm nơi nhận</h2>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Loại
            <select className={input} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as 'telegram' | 'mezon', address: '' })}><option value="telegram">Telegram (nhóm)</option><option value="mezon">Mezon (webhook)</option></select></label>
          <label className="flex min-w-64 flex-1 flex-col gap-1.5 text-[13px] font-semibold">{f.kind === 'telegram' ? 'Mã nhóm Telegram' : 'Địa chỉ webhook của kênh Mezon'}
            <input className={input} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder={f.kind === 'telegram' ? '-1001234567890' : 'https://webhook.mezon.ai/…'} /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên gợi nhớ
            <input className={input} value={f.label} maxLength={60} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="Nhóm tư vấn" /></label>
          <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Nhận tin của
            <select className={input} value={f.sandbox_id} onChange={(e) => setF({ ...f, sandbox_id: e.target.value })}><option value="">Cả doanh nghiệp</option>{q.data.sandboxes.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>
          <Button variant="primary" type="submit" busy={add.isPending} disabled={f.address.trim().length < 3}><Plus className="size-4" aria-hidden />Thêm</Button>
        </div>
        {add.isError && <p role="alert" className="text-[13px] text-bad">{explain(add.error)}</p>}
        <p className="text-xs text-ink-3">Địa chỉ webhook là chìa khoá vào kênh của bạn: sau khi lưu, màn hình chỉ hiện tên máy chủ.</p>
      </form></Card>
    </div>
  )
}
