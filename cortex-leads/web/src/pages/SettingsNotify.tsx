import { Plus, Send } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useAddTarget, useNotifyTargets, useRemoveTarget, useTestTarget } from '../api/hooks'
import type { NotifyTarget } from '../api/types'
import { SCard, SHead, fieldCls } from '../components/settingsUi'
import { Badge, Button, ErrorBox, Loading, Notice } from '../components/ui'

const KIND = { telegram: 'Telegram', mezon: 'Mezon' } as const

function Row({ t }: { t: NotifyTarget }) {
  const test = useTestTarget()
  const remove = useRemoveTarget()
  const [ask, setAsk] = useState(false)
  const err = test.error ?? remove.error
  return (
    <div role="row" className="flex flex-col gap-2 border-b border-line px-6 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3">
        <span className="min-w-0 flex-1 basis-48"><span className="flex items-center gap-2"><b className="truncate text-sm">{t.label || KIND[t.kind]}</b><Badge>{KIND[t.kind]}</Badge></span>
          <span className="mt-1 block truncate text-xs text-ink-2">{t.sandbox ? `Chỉ của «${t.sandbox}»` : 'Chung cho cả doanh nghiệp'} · <span className="font-mono">{t.address}</span></span></span>
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
  // a server with no Telegram bot cannot deliver there: the choice is not offered, rather than offered with a server setting to explain
  const kind = q.data.telegram_ready ? f.kind : 'mezon'
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate({ kind, address: f.address.trim(), label: f.label.trim() || undefined, sandbox_id: q.data.sandboxes.length > 1 ? f.sandbox_id || null : null }, { onSuccess: () => setF({ ...f, address: '', label: '' }) }) }
  return (
    <>
      <Notice tone="accent">Khi có khách cần người trả lời, hoặc có lịch học thử mới, hệ thống nhắn vào các nơi dưới đây. Tin chỉ có số lượng và đường dẫn, không có tên, số điện thoại hay lời của khách.</Notice>
      {!q.data.telegram_ready && q.data.items.some((t) => t.kind === 'telegram') && <Notice tone="warn">Máy chủ đang tắt Telegram nên các nơi nhận Telegram dưới đây tạm không nhận được tin. Nhờ người hỗ trợ kỹ thuật bật lại.</Notice>}
      <SCard>
        <SHead title="Nơi nhận thông báo" desc="Nhân viên cũng thấy khách cần người khi mở Hộp thư." />
        {q.data.items.length === 0 ? <p className="px-6 py-8 text-center text-[13px] text-ink-3">Chưa có nơi nhận nào. Nhân viên sẽ chỉ thấy khách cần người khi mở hộp thư.</p> : q.data.items.map((t) => <Row key={t.id} t={t} />)}
      </SCard>
      <SCard><form onSubmit={submit}>
        <SHead title="Thêm nơi nhận" />
        <div className="flex flex-col gap-4 px-6 py-5">
          <div className="grid gap-4 sm:grid-cols-3">
            {q.data.telegram_ready && <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Loại
              <select className={fieldCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as 'telegram' | 'mezon', address: '' })}><option value="telegram">Telegram (nhóm)</option><option value="mezon">Mezon (webhook)</option></select></label>}
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">{kind === 'telegram' ? 'Mã nhóm Telegram' : 'Địa chỉ webhook Mezon'}
              <input className={fieldCls} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} placeholder={kind === 'telegram' ? '-1001234567890' : 'https://webhook.mezon.ai/…'} /></label>
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold">Tên gợi nhớ
              <input className={fieldCls} value={f.label} maxLength={60} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="Nhóm tư vấn" /></label>
          </div>
          <div className="flex flex-wrap items-end gap-4">
            {q.data.sandboxes.length > 1 && <label className="flex w-72 max-w-full flex-col gap-1.5 text-[13px] font-semibold">Nhận tin của
              <select className={fieldCls} value={f.sandbox_id} onChange={(e) => setF({ ...f, sandbox_id: e.target.value })}><option value="">Cả doanh nghiệp</option>{q.data.sandboxes.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>}
            <Button variant="primary" type="submit" className="h-10" busy={add.isPending} disabled={f.address.trim().length < 3}><Plus className="size-4" aria-hidden />Thêm</Button>
          </div>
          {add.isError && <p role="alert" className="text-[13px] text-bad">{explain(add.error)}</p>}
          <p className="text-xs text-ink-3">Địa chỉ webhook là chìa khoá vào kênh của bạn: sau khi lưu, màn hình chỉ hiện tên máy chủ.</p>
        </div>
      </form></SCard>
    </>
  )
}
