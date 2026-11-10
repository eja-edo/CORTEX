import { Copy, MessageCircle, Plus } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { explain } from '../api/client'
import { useAddChannel, useChannels, useRemoveChannel } from '../api/hooks'
import type { ChannelItem, NewChannelResult } from '../api/types'
import { Time } from '../components/Time'
import { SCard, SHead, fieldCls } from '../components/settingsUi'
import { Badge, Button, ErrorBox, Loading, Notice } from '../components/ui'

const KIND: Record<string, string> = { messenger: 'Messenger', zalo_oa: 'Zalo OA', web: 'Web chat' }

/** The one moment the secret exists in clear. It is not kept by the page beyond this box. */
function SecretBox({ made, onClose }: { made: NewChannelResult; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const env = `CL_INGEST_URL=${made.ingest_url ?? '<địa chỉ máy chủ>/ingest/v1/events'}\nCL_CONNECTOR_ID=${made.id}\nCL_CONNECTOR_SECRET=${made.secret}`
  return (
    <Notice tone="warn"><span className="flex flex-col gap-2">
      <b>Đã tạo kênh {KIND[made.kind] ?? made.kind}.</b>
      <span>Bấm <b>Chép</b> rồi gửi khối mã dưới cho người hỗ trợ kỹ thuật để họ nối kênh với Fanpage. Mã <b>chỉ hiện một lần</b>; mất mã thì tạo kênh mới và tắt kênh này.</span>
      <pre aria-label="Cấu hình bridge" className="overflow-x-auto rounded bg-surface px-3 py-2 font-mono text-xs">{env}</pre>
      <span className="flex gap-2"><Button onClick={() => { void navigator.clipboard?.writeText(env); setCopied(true) }}><Copy className="size-4" aria-hidden />{copied ? 'Đã chép' : 'Chép'}</Button>
        <Button onClick={onClose}>Đã lưu, đóng</Button></span></span></Notice>
  )
}

function Row({ c }: { c: ChannelItem }) {
  const remove = useRemoveChannel()
  const [ask, setAsk] = useState(false)
  const off = c.status === 'disabled'
  return (
    <div role="row" className="flex flex-col gap-2 border-b border-line px-6 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center gap-3.5">
        <span className="grid size-10 shrink-0 place-items-center rounded-[10px] bg-accent-soft text-accent"><MessageCircle className="size-5" aria-hidden /></span>
        <span className="min-w-0 flex-1 basis-48"><b className="block truncate text-sm">{KIND[c.kind] ?? c.kind}</b><span className="block truncate text-xs text-ink-2">{c.sandbox ?? '—'} · <span className="font-mono">{c.id}</span></span></span>
        <span className="flex flex-col items-end gap-1"><Badge tone={off ? 'bad' : 'ok'}>{off ? 'Đã tắt' : 'Đang bật'}</Badge>
          <span className="text-xs text-ink-3">{c.last_event_at ? <>Tin gần nhất <Time iso={c.last_event_at} as="when" /></> : 'Chưa nhận tin nào'}</span></span>
        {!off && (ask ? <><span className="text-xs">Tắt kênh này? Bridge sẽ bị từ chối.</span><Button variant="dangerSolid" busy={remove.isPending} onClick={() => remove.mutate(c.id, { onSettled: () => setAsk(false) })}>Tắt</Button><Button onClick={() => setAsk(false)}>Không</Button></>
          : <Button variant="danger" onClick={() => setAsk(true)}>Tắt kênh</Button>)}
      </div>
      {remove.isError && <p role="alert" className="text-xs text-bad">{explain(remove.error)}</p>}
    </div>
  )
}

export function SettingsChannels() {
  const q = useChannels()
  const add = useAddChannel()
  const [made, setMade] = useState<NewChannelResult | null>(null)
  const [f, setF] = useState({ kind: 'messenger', sandbox_id: '' })
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const sandbox = f.sandbox_id || q.data.sandboxes[0]?.id || ''
  const submit = (e: FormEvent) => { e.preventDefault(); add.mutate({ kind: f.kind, sandbox_id: sandbox }, { onSuccess: setMade }) }
  return (
    <>
      {made && <SecretBox made={made} onClose={() => setMade(null)} />}
      <SCard>
        <SHead title="Kênh đang dùng" desc="Nơi khách nhắn vào. Mỗi kênh đưa tin vào một việc của AI." />
        {q.data.items.length === 0 ? <p className="px-6 py-8 text-center text-[13px] text-ink-3">Chưa nối kênh nào. Tạo một kênh bên dưới để tin của khách chảy vào hệ thống.</p> : q.data.items.map((c) => <Row key={c.id} c={c} />)}
      </SCard>
      <SCard><form onSubmit={submit}>
        <SHead title="Thêm kênh mới" />
        <div className="flex flex-wrap items-end gap-4 px-6 py-5">
          <label className="flex min-w-40 flex-1 flex-col gap-1.5 text-[13px] font-semibold">Loại kênh
            <select className={fieldCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{q.data.kinds.map((k) => <option key={k} value={k}>{KIND[k] ?? k}</option>)}</select></label>
          {q.data.sandboxes.length > 1 && <label className="flex min-w-40 flex-1 flex-col gap-1.5 text-[13px] font-semibold">Đưa tin vào
            <select className={fieldCls} value={sandbox} onChange={(e) => setF({ ...f, sandbox_id: e.target.value })}>{q.data.sandboxes.map((s) => <option key={s.id} value={s.id}>{s.title}</option>)}</select></label>}
          <Button variant="primary" type="submit" className="h-10" busy={add.isPending} disabled={!sandbox}><Plus className="size-4" aria-hidden />Tạo kênh</Button>
          {q.data.sandboxes.length === 1 && <p className="min-w-40 flex-[2] self-center text-[13px] text-ink-2">Tin của khách sẽ đi vào «{q.data.sandboxes[0].title}».</p>}
          {q.data.sandboxes.length === 0 && <p className="w-full text-[13px] text-ink-3">Thiếu việc «Chăm sóc khách» của AI. Nhờ người hỗ trợ kỹ thuật thêm.</p>}
          {add.isError && <p role="alert" className="w-full text-[13px] text-bad">{explain(add.error)}</p>}
          {!q.data.ingest_url && <p className="w-full text-xs text-ink-3">Máy chủ chưa có <code>CL_PUBLIC_BASE_URL</code>, nên địa chỉ nhận tin sẽ để trống trong cấu hình bridge.</p>}
        </div>
      </form></SCard>
    </>
  )
}
