import { AlertTriangle, ArchiveRestore, Database, Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useMoveSource, useSandboxes, useSource, useSourceVerb, useSources, useTools } from '../api/hooks'
import type { SourceItem, ToolLevel } from '../api/types'
import { Time } from '../components/Time'
import { Badge, Button, Card, Empty, ErrorBox, Label, Loading, Notice, PageHeader, Tabs, type Tone } from '../components/ui'

export const LEVEL_TONE: Record<ToolLevel, Tone> = { read: 'accent', internal: 'warn', customer: 'bad', external: 'ai' }
const LEVEL_TEXT: Record<ToolLevel, string> = {
  read: 'Chỉ lấy thông tin. AI tự gọi được trong lúc suy nghĩ.',
  internal: 'Ghi vào hệ thống của mình, hoàn tác được. Chỉ hệ thống gọi sau khi AI quyết định, AI không tự bấm.',
  customer: 'Tới khách thật. Chỉ có một công cụ, qua một đường, và có thể bị chặn ở kỹ năng, ở kênh và khi sandbox đang dừng.',
  external: 'Dữ liệu từ bên ngoài, không đáng tin. Chỉ gắn cho sandbox không nói chuyện với khách; sau khi đọc, lượt đó không được ghi gì.',
}
type Tab = 'tools' | 'sources' | 'channels'

function ToolsTab() {
  const q = useTools()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  return (
    <div className="flex min-h-0 gap-5">
      <Card className="min-w-0 flex-1 overflow-hidden">
        <div role="row" className="flex gap-3 bg-app px-4 py-3 text-[11px] font-semibold tracking-wider text-ink-3 uppercase"><span className="flex-1">Công cụ</span><span className="w-28">Mức</span><span className="w-56">Sandbox được dùng</span><span className="w-24">Kỹ năng dùng</span></div>
        {q.data.items.map((t) => (
          <div key={t.name} role="row" className="flex items-center gap-3 border-t border-line px-4 py-3">
            <span className="min-w-0 flex-1"><b className="block text-sm">{t.label}</b><span className="block text-xs text-ink-2">{t.about}</span></span>
            <span className="w-28"><Badge tone={LEVEL_TONE[t.level]}>{t.level_label}</Badge></span>
            <span className="flex w-56 flex-col gap-1 text-[13px]">{t.sandboxes.map((s) => <Link key={s.id} to={`/sandboxes/${s.id}?tab=tools&tool=${t.name}`} className={s.on ? 'text-ink hover:underline' : 'text-ink-3 line-through'}>{s.title}{s.on ? '' : ' (đã tắt)'}</Link>)}</span>
            <span className="w-24 text-[13px] font-semibold">{t.skills}</span>
          </div>))}
      </Card>
      <Card className="flex w-80 shrink-0 flex-col gap-3 self-start p-5">
        <h2 className="text-[15px] font-bold">Ba mức quyền của công cụ</h2>
        {(Object.keys(LEVEL_TEXT) as ToolLevel[]).map((l) => <div key={l} className="flex flex-col gap-1.5"><Badge tone={LEVEL_TONE[l]} className="self-start">{q.data.levels[l]}</Badge><p className="text-xs leading-snug text-ink-2">{LEVEL_TEXT[l]}</p></div>)}
      </Card>
    </div>
  )
}

const STATE: Record<SourceItem['state'], [string, Tone]> = { active: ['Đang dùng', 'ok'], alert: ['Đã tự khoá', 'bad'], locked: ['Đã khoá', 'neutral'], deleted: ['Đã khoá (xoá)', 'neutral'] }

function SourceDetailPanel({ id, onGone }: { id: string; onGone: () => void }) {
  const q = useSource(id)
  const verb = useSourceVerb()
  const move = useMoveSource()
  const [ask, setAsk] = useState(false)
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const d = q.data
  const deleted = d.state === 'deleted'
  const row = (k: string, v: string | null) => <div key={k}><dt className="text-[11px] text-ink-3">{k}</dt><dd className="break-all text-[13px] font-medium">{v ?? '–'}</dd></div>
  return (
    <div className="flex flex-col gap-4">
      <div><h2 className="text-base font-bold">{d.name}</h2><div className="mt-1.5 flex gap-1.5"><Badge tone={STATE[d.state][1]}>{STATE[d.state][0]}</Badge><Badge>{d.kind_label}</Badge></div></div>
      {d.alert && <Notice tone="bad"><span><b>{d.alert}.</b> Nguồn này đã tạm khoá để tránh bị đổi ý nghĩa công cụ.{d.kind === 'mcp' && !deleted && ' Xem thay đổi và duyệt lại nếu bạn tin tưởng.'}</span></Notice>}
      {d.alert && d.kind === 'mcp' && !deleted && <Button variant="primary" busy={verb.isPending} onClick={() => verb.mutate({ id, verb: 'review' })}>Duyệt lại định nghĩa mới</Button>}
      <Label>Cấu hình đã ghim</Label>
      <dl className="flex flex-col gap-2.5">
        {row('Loại', d.kind === 'mcp' ? `MCP server, chỉ đọc${d.pinned_tools.length ? ` · công cụ ${d.pinned_tools.join(', ')}` : ''}` : 'Nguồn HTTP, chỉ GET')}
        {row('Địa chỉ', d.url)}{row('Máy chủ được gọi', d.allow_hosts.join(', '))}
        {row('Khoá truy cập', d.auth_saved ? 'Đã lưu, mã hoá (không hiện lại)' : 'Không dùng khoá')}{row('Mã ghim', d.pin)}
      </dl>
      <p className="text-xs text-ink-3">{d.pin_ok ? 'Cấu hình khớp mã ghim. Sửa địa chỉ, máy chủ hay công cụ sẽ tính lại mã ghim và cần bạn xem lại định nghĩa một lần nữa.' : 'Cấu hình KHÔNG còn khớp mã ghim: nguồn từ chối chạy.'}</p>
      <div className="flex flex-col gap-1.5"><Label>Gắn cho sandbox</Label>
        {d.attachable.map((s) => <label key={s.id} className="flex items-center gap-2 text-[13px]"><input type="radio" name="sb" checked={d.sandbox?.id === s.id} disabled={deleted || move.isPending}
          onChange={() => move.mutate({ id, sandbox_id: s.id })} />{s.title}</label>)}
        <p className="text-xs text-ink-3">Sandbox có nói chuyện với khách thì không gắn được: dữ liệu ngoài là thứ không đáng tin.</p>
        {move.isError && <Notice tone="bad">{explain(move.error)}</Notice>}</div>
      <div className="flex flex-col gap-1"><Label>7 ngày qua</Label><p className="text-[13px]">{d.calls_7d} lượt gọi · {d.errors_7d} lỗi{d.last_at && <> · gần nhất <Time iso={d.last_at} as="when" /></>}</p></div>
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      {deleted ? <Button variant="primary" busy={verb.isPending} onClick={() => verb.mutate({ id, verb: 'unlock' }, { onSuccess: onGone })}><ArchiveRestore className="size-4" aria-hidden />Khôi phục nguồn này</Button> : (
        <Card className="flex flex-col gap-2 border-bad p-4"><h3 className="text-[13px] font-bold text-bad">Khoá nguồn này (xoá mềm)</h3>
          <p className="text-xs text-ink-2">Nguồn ngừng hoạt động ngay và biến mất khỏi danh sách. Cấu hình và lịch sử gọi vẫn được giữ, khôi phục được. Công cụ nguồn ngoài sẽ báo không tìm thấy nguồn này trong lúc bị khoá.</p>
          {ask ? <div className="flex gap-2"><Button variant="dangerSolid" className="flex-1" busy={verb.isPending} onClick={() => verb.mutate({ id, verb: 'lock' }, { onSuccess: () => { setAsk(false); onGone() } })}>Khoá nguồn</Button><Button className="flex-1" onClick={() => setAsk(false)}>Không</Button></div>
            : <Button variant="danger" onClick={() => setAsk(true)}>Khoá nguồn này</Button>}
        </Card>)}
    </div>
  )
}

function SourcesTab() {
  const q = useSources()
  const [picked, setPicked] = useState<string | null>(null)
  const [showDeleted, setShowDeleted] = useState(false)
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const items = q.data.items.filter((s) => (s.state === 'deleted') === showDeleted)
  return (
    <div className="flex min-h-0 gap-5">
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div className="flex items-center justify-between"><div className="flex gap-2 text-[13px]">
          <button className={showDeleted ? 'text-ink-2' : 'font-semibold text-accent'} onClick={() => setShowDeleted(false)}>Đang có ({q.data.counts.all})</button>
          <button className={showDeleted ? 'font-semibold text-accent' : 'text-ink-2'} onClick={() => setShowDeleted(true)}>Đã khoá ({q.data.counts.deleted})</button></div>
          <Link to="/tools/sources/new"><Button variant="primary"><Plus className="size-4" aria-hidden />Thêm nguồn dữ liệu</Button></Link></div>
        {items.length === 0 && <Card><Empty>{showDeleted ? 'Không có nguồn nào bị khoá.' : 'Chưa có nguồn dữ liệu nào. Nguồn ngoài chỉ gắn cho sandbox không nói chuyện với khách.'}</Empty></Card>}
        {items.map((s) => (
          <button key={s.id} onClick={() => setPicked(s.id)} aria-pressed={picked === s.id} className={`flex flex-col gap-2 rounded-xl border bg-surface p-4 text-left ${picked === s.id ? 'border-accent' : s.state === 'alert' ? 'border-bad' : 'border-line'}`}>
            <div className="flex items-center gap-2"><Database className="size-4 text-ink-3" aria-hidden /><b className="text-sm">{s.name}</b><Badge tone={STATE[s.state][1]}>{STATE[s.state][0]}</Badge></div>
            <p className="text-xs text-ink-2">{s.kind_label} · {s.host}{s.pinned_tools.length > 0 && ` · công cụ ghim ${s.pinned_tools.join(', ')}`}</p>
            <p className="text-xs text-ink-2">Gắn cho <b>{s.sandbox?.title}</b> · {s.calls_7d} lượt gọi tuần này{s.last_at && <> · gần nhất <Time iso={s.last_at} as="when" /></>}</p>
            {s.alert && <p className="flex items-center gap-1.5 text-xs font-semibold text-bad"><AlertTriangle className="size-3.5" aria-hidden />{s.alert}</p>}
          </button>))}
      </div>
      <Card className="w-96 shrink-0 self-start p-5">{picked ? <SourceDetailPanel key={picked} id={picked} onGone={() => setPicked(null)} /> : <Empty>Chọn một nguồn để xem cấu hình đã ghim.</Empty>}</Card>
    </div>
  )
}

function ChannelsTab() {
  const q = useSandboxes()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const rows = q.data.items.flatMap((sb) => sb.channels.map((c) => ({ sb, c })))
  return (
    <Card className="max-w-3xl overflow-hidden">
      {rows.length === 0 ? <Empty>Chưa có kênh nào nối với khách.</Empty> : rows.map(({ sb, c }, i) => (
        <div key={i} className="flex items-center gap-3 border-t border-line px-4 py-3 first:border-0"><b className="flex-1 text-sm">{c.kind === 'messenger' ? 'Messenger' : c.kind}</b>
          <span className="text-[13px] text-ink-2">{sb.title}</span><Badge tone={c.status === 'active' ? 'ok' : 'neutral'}>{c.status === 'active' ? 'Đang nối' : 'Tắt'}</Badge>
          <Badge>{c.sends ? 'Được gửi từ hệ thống' : 'Chỉ nhận, nhân viên tự gửi'}</Badge></div>))}
    </Card>
  )
}

export function Tools() {
  const counts = useTools().data?.counts
  const [tab, setTab] = useState<Tab>('tools')
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-8">
      <PageHeader title="Công cụ & kết nối" subtitle="Công cụ là thứ AI làm được. Nguồn dữ liệu và kênh là nơi công cụ lấy thông tin hoặc gửi đi. Mỗi thứ chỉ gắn cho những sandbox bạn chọn." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'tools', label: 'Công cụ', count: counts?.tools }, { id: 'sources', label: 'Nguồn dữ liệu & MCP', count: counts?.sources }, { id: 'channels', label: 'Kênh', count: counts?.channels }]} />
      {tab === 'tools' && <ToolsTab />}{tab === 'sources' && <SourcesTab />}{tab === 'channels' && <ChannelsTab />}
    </div>
  )
}
