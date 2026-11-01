import clsx from 'clsx'
import { Boxes } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useCreateSandbox, useSandboxVerb, useSandboxes, useSession } from '../api/hooks'
import type { SandboxItem, SandboxTemplate } from '../api/types'
import { compact } from '../components/format'
import { Badge, Button, Card, ErrorBox, Label, Loading, Meter, Notice, PageHeader } from '../components/ui'

const MODES: Record<SandboxItem['send_mode'], string> = { manual: 'Chế độ nháp', auto: 'Tự gửi khi đủ điều kiện' }

function SandboxCard({ sb, owner }: { sb: SandboxItem; owner: boolean }) {
  const verb = useSandboxVerb()
  const paused = sb.status === 'paused'
  return (
    <Card className="flex flex-col gap-4 p-5">
      <div className="flex items-center gap-2.5">
        <span className="flex size-9 items-center justify-center rounded-lg bg-accent-soft text-accent" aria-hidden><Boxes className="size-[18px]" /></span>
        <div className="min-w-0 flex-1"><h2 className="truncate text-base font-bold">{sb.title}</h2><p className="truncate text-xs text-ink-2">{sb.about}</p></div>
        <Badge tone={paused ? 'bad' : 'ok'}>{paused ? 'Đang tạm dừng' : 'Đang chạy'}</Badge>
        <Badge>{sb.customer_facing ? MODES[sb.send_mode] : sb.purpose === 'owner_digest' ? 'Chỉ đọc số liệu' : 'Không nhắn khách'}</Badge>
      </div>
      <div className="flex gap-6">
        <Meter label="Lượt chạy hôm nay" value={sb.usage.runs} total={sb.budget.runs_per_day} />
        <Meter label="Token hôm nay" value={sb.usage.tokens} total={sb.budget.tokens_per_day} tone="ai" />
      </div>
      <dl className="flex gap-8 text-[13px]">
        <div><dt className="text-[11px] text-ink-3">Kỹ năng đang bật</dt><dd className="font-medium">{sb.skills.live}{sb.skills.shadow ? ` (${sb.skills.shadow} đang thử)` : ''}</dd></div>
        {sb.customer_facing
          ? <div><dt className="text-[11px] text-ink-3">Kênh nối</dt><dd className="font-medium">{sb.channels.length ? sb.channels.map((c) => `${c.kind === 'messenger' ? 'Messenger' : c.kind}${c.sends ? '' : ' (chỉ nhận)'}`).join(', ') : 'Chưa nối kênh khách'}</dd></div>
          : sb.flow && <div><dt className="text-[11px] text-ink-3">Luồng</dt><dd className="font-medium">{sb.flow}</dd></div>}
        <div><dt className="text-[11px] text-ink-3">Token tối đa mỗi ngày</dt><dd className="font-medium">{sb.budget.tokens_per_day ? compact(sb.budget.tokens_per_day) : '–'}</dd></div>
      </dl>
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      {owner && <div className="flex gap-2">
        <Link to={`/sandboxes/${sb.id}`}><Button>Xem chi tiết</Button></Link>
        {sb.purpose === 'customer_care' && <Link to={`/sandboxes/${sb.id}?tab=send`}><Button>Đổi chế độ gửi</Button></Link>}
        {paused ? <Button variant="primary" busy={verb.isPending} onClick={() => verb.mutate({ id: sb.id, verb: 'resume' })}>Bật lại sandbox</Button>
          : <Button variant="danger" busy={verb.isPending} onClick={() => verb.mutate({ id: sb.id, verb: 'pause' })}>Tạm dừng sandbox</Button>}
      </div>}
    </Card>
  )
}

function CreatePanel({ templates }: { templates: SandboxTemplate[] }) {
  const create = useCreateSandbox()
  const [tpl, setTpl] = useState<SandboxTemplate['id']>('customer_care')
  const [title, setTitle] = useState('')
  const done = create.isSuccess
  return (
    <Card className="flex w-96 shrink-0 flex-col gap-4 self-start p-5">
      <div><h2 className="text-base font-bold">Tạo sandbox mới</h2><p className="mt-1 text-xs leading-snug text-ink-2">Chọn mẫu. Mỗi mẫu đã có sẵn bộ công cụ an toàn và hồ sơ AI phù hợp.</p></div>
      <div role="radiogroup" aria-label="Mẫu sandbox" className="flex flex-col gap-2.5">
        {templates.map((t) => (
          <button key={t.id} role="radio" aria-checked={tpl === t.id} aria-disabled={!t.available} onClick={() => t.available && setTpl(t.id)}
            className={clsx('flex gap-3 rounded-[10px] border p-3.5 text-left', tpl === t.id ? 'border-2 border-accent bg-accent-soft' : 'border-line', !t.available && 'opacity-55')}>
            <span className={clsx('mt-0.5 size-4 shrink-0 rounded-full border', tpl === t.id ? 'border-accent bg-accent' : 'border-line bg-app')} aria-hidden />
            <span className="flex flex-col gap-1"><b className="text-sm">{t.label}</b><span className="text-xs leading-snug text-ink-2">{t.description}</span>
              {!t.available && <Badge tone="warn" className="self-start">{t.reason}</Badge>}</span>
          </button>))}
      </div>
      <label className="flex flex-col gap-1.5 text-xs font-medium text-ink-2">Tên sandbox
        <input value={title} onChange={(e) => { setTitle(e.target.value); create.reset() }} placeholder="Chăm sóc khách – cơ sở 2" className="rounded-lg border border-line px-3 py-2.5 text-sm font-normal text-ink" /></label>
      <p className="text-xs leading-snug text-ink-3">Sandbox mới bắt đầu ở chế độ nháp và có ngân sách mặc định; bạn đổi sau.</p>
      {create.isError && <Notice tone="bad">{explain(create.error)}</Notice>}
      {done && <Notice tone="ok">Đã tạo sandbox “{title.trim()}”.</Notice>}
      <Button variant="primary" busy={create.isPending} disabled={title.trim().length < 3} onClick={() => create.mutate({ template: tpl, title: title.trim() })}>Tạo sandbox</Button>
    </Card>
  )
}

export function Sandboxes() {
  const { data: me } = useSession()
  const q = useSandboxes()
  const owner = me?.role === 'owner'
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <PageHeader title="Sandbox" subtitle="Mỗi sandbox là một không gian AI làm một loại việc, tách biệt dữ liệu và công cụ với các sandbox khác." />
      {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : (
        <div className="flex gap-5">
          <div className="flex min-w-0 flex-1 flex-col gap-4">
            {q.data.items.length === 0 && <Notice tone="warn">Chưa có sandbox nào. Tạo sandbox “Chăm sóc khách” để bắt đầu.</Notice>}
            {q.data.items.map((sb) => <SandboxCard key={sb.id} sb={sb} owner={!!owner} />)}
          </div>
          {owner ? <CreatePanel templates={q.data.templates} /> : <Card className="w-96 shrink-0 self-start p-5"><Label>Tạo sandbox</Label><p className="mt-2 text-[13px] text-ink-2">Chỉ chủ mới tạo được sandbox mới.</p></Card>}
        </div>)}
    </div>
  )
}
