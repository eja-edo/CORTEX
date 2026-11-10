import clsx from 'clsx'
import { ArrowRight, Check, Lock, Minus, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { explain } from '../api/client'
import { useSandbox, useSandboxes, useSession, useSwitchTool, useToolInSandbox } from '../api/hooks'
import type { Cell, SandboxDetail as Detail, SkillStatus } from '../api/types'
import { can } from '../components/can'
import { compact } from '../components/format'
import { Badge, Card, ErrorBox, Label, Loading, Meter, Notice, PageHeader, SidePanel, Tabs, type Tone } from '../components/ui'
import { skillTitle } from '../components/skillName'
import { LEVEL_TONE } from './Tools'
import { Perm } from '../api/enums'

type Tab = 'overview' | 'tools' | 'send' | 'data' | 'budget'
const PUSH_TONE = (active: boolean): Tone => (active ? 'ok' : 'neutral')
const SKILL: Record<SkillStatus, [string, Tone]> = { live: ['Đang bật', 'ok'], shadow: ['Chạy thử', 'warn'], draft: ['Bản nháp', 'neutral'], retired: ['Đã tắt', 'neutral'] }
const CELL: Record<Cell, { label: string; icon: ReactNode; cls: string }> = {
  uses: { label: 'Kỹ năng dùng', icon: <Check className="size-4" />, cls: 'bg-accent text-white' },
  allowed: { label: 'Cho phép, kỹ năng không dùng', icon: <Minus className="size-4" />, cls: 'border border-line text-ink-3' },
  blocked: { label: 'Kỹ năng cần nhưng việc này đã tắt', icon: <X className="size-4" />, cls: 'bg-bad-soft text-bad' },
  off: { label: 'Việc này đã tắt', icon: <X className="size-4" />, cls: 'text-ink-3' },
  locked: { label: 'Bị khoá với kỹ năng từ form', icon: <Lock className="size-3.5" />, cls: 'bg-app text-ink-3' },
}

function Overview({ d }: { d: Detail }) {
  const on = d.tools.filter((t) => t.on)
  return (
    <div className="flex flex-col gap-4">
      {d.facing.tools && <Notice tone="ai"><span><b>AI chỉ dùng được công cụ nằm trong cả hai danh sách.</b> Danh sách của việc này (hồ sơ AI, giới hạn quyền cao nhất) và danh sách của kỹ năng đang chạy. Kỹ năng không thể xin thêm quyền mà việc này không cho.</span></Notice>}
      <div className="flex flex-col gap-3 xl:flex-row xl:items-start">
        <Card className="flex shrink-0 flex-col gap-3 p-4 xl:w-64"><Label>Đầu vào</Label>
          {d.facing.customer && <>
            {d.inputs.channels.map((c, i) => <div key={i} className="rounded-lg bg-app p-3 text-[13px]"><b>{c.kind === 'messenger' ? 'Messenger' : c.kind}</b><p className="text-xs text-ink-2">{c.sends ? 'Được gửi từ hệ thống' : 'Chỉ nhận'}</p></div>)}
            {d.inputs.channels.length === 0 && <p className="text-xs text-ink-3">Chưa nối kênh khách</p>}
            <div className="rounded-lg bg-app p-3 text-[13px]"><b>Catalog nội bộ</b><p className="text-xs text-ink-2">{d.inputs.catalog_items} mục: khoá, giá, lịch học thử</p></div></>}
          {d.feeds.map((f) => <div key={f.id} className="rounded-lg bg-app p-3 text-[13px]"><b>{f.label}</b><p className="text-xs text-ink-2">{f.where} · {f.active ? 'đang theo dõi' : 'tạm dừng'}</p></div>)}
          {!d.facing.customer && d.feeds.length === 0 && d.inputs.sources.length === 0 && <p className="text-xs text-ink-3">Chưa gắn nguồn nào</p>}
          {d.inputs.sources.map((s) => <div key={s.id} className="rounded-lg bg-ai-soft p-3 text-[13px]"><b>{s.name}</b><p className="text-xs text-ink-2">Nguồn ngoài, chỉ đọc</p></div>)}
        </Card>
        <ArrowRight className="size-5 shrink-0 rotate-90 self-center text-ink-3 xl:mt-24 xl:rotate-0 xl:self-start" aria-hidden />
        <Card className="flex min-w-0 flex-1 flex-col gap-3 p-4"><Label>Việc của AI</Label>
          <h2 className="text-base font-bold">{d.title}</h2>
          <dl className="grid grid-cols-2 gap-3 text-[13px]"><div><dt className="text-[11px] text-ink-3">Hồ sơ AI</dt><dd className="font-medium">{d.profile.id} · bản {d.profile.version}</dd></div>
            <div><dt className="text-[11px] text-ink-3">Quyền cao nhất</dt><dd className="font-medium">{d.profile.ceiling}</dd></div>
            <div><dt className="text-[11px] text-ink-3">Công cụ</dt><dd className="font-medium">{d.facing.tools ? `Tối đa ${d.profile.max_tool_calls} lần mỗi lượt` : 'Không dùng: AI chỉ đọc và viết'}</dd></div>
            <div><dt className="text-[11px] text-ink-3">Dữ liệu</dt><dd className="font-medium">Tách theo doanh nghiệp</dd></div></dl>
          {d.facing.tools && <><Label>Công cụ được phép · {on.length}</Label>
            <div className="flex flex-wrap gap-1.5">{on.map((t) => <Badge key={t.name} tone={LEVEL_TONE[t.level]}>{t.label}</Badge>)}{on.length === 0 && <span className="text-xs text-ink-3">Không có công cụ nào.</span>}</div></>}
          {d.pushes.length > 0 && <><Label>Gửi tới · {d.pushes.length}</Label>
            <div className="flex flex-col gap-1.5">{d.pushes.map((p) => <div key={p.id} className="flex flex-wrap items-center gap-2 text-[13px]"><b>{p.label}</b><span className="text-xs text-ink-2">{p.where}</span><Badge tone={PUSH_TONE(p.active)}>{p.active ? 'Đang dùng' : 'Tắt'}</Badge></div>)}</div></>}
        </Card>
        <ArrowRight className="size-5 shrink-0 rotate-90 self-center text-ink-3 xl:mt-24 xl:rotate-0 xl:self-start" aria-hidden />
        <Card className="flex shrink-0 flex-col gap-3 p-4 xl:w-80"><Label>Kỹ năng · {d.skills.length}</Label>
          {d.skills.map((s) => <Link key={s.id} to={`/skills/${s.id}`} className="rounded-lg bg-app p-3 text-[13px] hover:bg-accent-soft"><b className="block">{skillTitle(s.name)}</b>
            <span className="block text-xs text-ink-2">{s.trigger}</span>{d.facing.tools && <span className="text-xs text-ink-2">Dùng {s.uses}/{s.total} công cụ · </span>}<Badge tone={SKILL[s.status][1]}>{SKILL[s.status][0]}</Badge></Link>)}
          {d.facing.customer && d.skills.some((s) => s.source === 'custom') && <p className="text-xs text-ink-3">Kỹ năng tạo từ form: không thể xin Gửi tin hay Giữ chỗ.</p>}
        </Card>
      </div>
    </div>
  )
}

/** The mode is read here and changed in one place: Cài đặt → AI (owner). Two screens that could both write it kept disagreeing in people's heads. */
function SettingsLink({ to, children }: { to: string; children: ReactNode }) {
  const { data: me } = useSession()
  return can(me, Perm.SETTINGS_MANAGE) ? <Link to={to} className="inline-flex items-center gap-1 text-[13px] font-semibold text-accent hover:underline">{children}<ArrowRight className="size-3.5" aria-hidden /></Link> : null
}

function SendPanel({ d }: { d: Detail }) {
  const auto = d.send.mode === 'auto'
  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <Card className="flex flex-col gap-2 p-5">
        <div className="flex flex-wrap items-center gap-3"><h2 className="text-[15px] font-bold">Chế độ gửi tin cho khách</h2><Badge tone={auto ? 'warn' : 'ok'}>{auto ? 'Tự gửi khi đủ điều kiện' : 'Duyệt tay'}</Badge></div>
        <p className="text-xs text-ink-2">{auto
          ? 'Chỉ các kỹ năng được phép tự gửi mới trả lời khách ngay mà không ai duyệt; kỹ năng khác vẫn chỉ soạn nháp.'
          : 'Mọi tin AI soạn chờ nhân viên bấm duyệt rồi mới gửi.'} Mọi tin, ở chế độ nào, đều đi qua cùng một đường và cùng các luật chặn.</p>
        {!d.send.auto_possible && auto && <p className="text-xs font-semibold text-bad">Hiện chưa có kênh nào được phép gửi từ hệ thống, nên tin vẫn chờ nhân viên.</p>}
        <SettingsLink to="/settings?tab=ai">Đổi ở Cài đặt → AI</SettingsLink>
      </Card>
      <Card className="flex flex-col gap-2 p-5"><Label>Từng kỹ năng</Label>
        {d.send.skills.map((s) => <div key={s.name} className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-line pt-2 first:border-0 first:pt-0"><b className="w-full text-[13px] sm:w-56">{skillTitle(s.name)}</b>
          <Badge tone={s.effective === 'auto' ? 'warn' : 'neutral'}>{s.effective === 'auto' ? 'Tự gửi' : 'Duyệt tay'}</Badge><span className="text-xs text-ink-2">{s.why}</span></div>)}
      </Card>
      <Card className="flex flex-col gap-2 p-5"><Label>Kênh</Label>
        {d.send.channels.length === 0 && <p className="text-[13px] text-ink-3">Chưa nối kênh nào.</p>}
        {d.send.channels.map((c, i) => <div key={i} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px]"><b className="w-28">{c.kind === 'messenger' ? 'Messenger' : c.kind}</b>
          <Badge tone={c.can_send ? 'ok' : 'neutral'}>{c.can_send ? 'Được gửi từ hệ thống' : 'Chỉ nhận'}</Badge>{c.problems.map((p) => <span key={p} className="text-xs text-ink-2">{p}</span>)}</div>)}
      </Card>
    </div>
  )
}

function ToolPanel({ sandbox, tool }: { sandbox: string; tool: string }) {
  const q = useToolInSandbox(sandbox, tool)
  const sw = useSwitchTool(sandbox)
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const t = q.data
  return (
    <div className="flex flex-col gap-3">
      <div><h2 className="text-base font-bold">{t.label}</h2><p className="font-mono text-xs text-ink-3">{t.name}</p><Badge tone={LEVEL_TONE[t.level]} className="mt-1.5">{t.level_label}</Badge></div>
      <p className="text-[13px] text-ink-2">{t.about}</p>
      <Label>Ở việc này</Label>
      <label className="flex items-center gap-2 text-[13px] font-medium"><input type="checkbox" role="switch" aria-label="Cho phép dùng" checked={t.on} disabled={sw.isPending} onChange={(e) => sw.mutate({ tool: t.name, on: e.target.checked })} />Cho phép dùng</label>
      {sw.isError && <Notice tone="bad">{explain(sw.error)}</Notice>}
      <Label>Kỹ năng đang dùng</Label>
      {t.skills.length ? t.skills.map((s) => <p key={s} className="text-[13px]">{skillTitle(s)}</p>) : <p className="text-xs text-ink-3">Chưa kỹ năng nào dùng.</p>}
      {t.safety.length > 0 && <><Label>An toàn</Label>{t.safety.map((x) => <p key={x} className="flex gap-2 text-[13px]"><Check className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />{x}</p>)}</>}
      {t.on && t.if_off && <Notice tone="warn"><span><b>Nếu tắt công cụ này</b><br />{t.if_off}</span></Notice>}
    </div>
  )
}

function Matrix({ d, sandbox, tool, onTool }: { d: Detail; sandbox: string; tool: string | null; onTool: (t: string | null) => void }) {
  return (
    <div className="flex gap-5 xl:items-start">
      <Card className="min-w-0 flex-1 overflow-x-auto p-5">
        <h2 className="text-[15px] font-bold">AI được dùng công cụ nào</h2>
        <p className="mb-3 text-xs text-ink-2">Hàng trên cùng là giới hạn của việc này. Mỗi kỹ năng chỉ dùng được phần giao giữa hàng đó và công cụ nó khai báo.</p>
        <table className="w-full text-center text-[13px]"><thead><tr className="text-[11px] text-ink-3">
          <th className="sticky left-0 z-10 bg-surface px-2 py-2 text-left font-semibold">KỸ NĂNG</th>{d.tools.map((t) => <th key={t.name} className="px-1 py-2 font-medium"><button className={clsx('rounded px-1 hover:underline', tool === t.name && 'font-bold text-accent')} onClick={() => onTool(t.name)}>{t.label}</button><br /><Badge tone={LEVEL_TONE[t.level]}>{t.level_label}</Badge></th>)}</tr></thead>
          <tbody>
            <tr className="border-t border-line bg-app"><td className="sticky left-0 z-10 bg-app px-2 py-2.5 text-left font-semibold">Việc này cho phép<span className="block text-[11px] font-normal text-ink-3">Đổi được (chủ)</span></td>
              {d.tools.map((t) => <td key={t.name} className="py-2.5"><span title={t.on ? 'Việc này cho phép' : 'Việc này đã tắt'} className={clsx('mx-auto flex size-6 items-center justify-center rounded-full', t.on ? 'bg-accent text-white' : 'bg-bad-soft text-bad')}>{t.on ? <Check className="size-4" /> : <X className="size-4" />}</span></td>)}</tr>
            {d.skills.map((s) => (
              <tr key={s.id} className="border-t border-line"><td className="sticky left-0 z-10 bg-surface px-2 py-2.5 text-left"><b className="block">{skillTitle(s.name)}</b><span className="text-[11px] text-ink-3">{SKILL[s.status][0]}{s.source === 'custom' ? ' · từ form' : ''}</span></td>
                {d.tools.map((t) => { const c = CELL[s.cells[t.name]]; return <td key={t.name} className="py-2.5"><span role="img" aria-label={`${skillTitle(s.name)} · ${t.label}: ${c.label}`} title={c.label} className={clsx('mx-auto flex size-6 items-center justify-center rounded-full', c.cls)}>{c.icon}</span></td> })}</tr>))}
          </tbody></table>
        <div className="mt-3 flex flex-wrap gap-4 text-xs text-ink-2">{(['uses', 'allowed', 'blocked', 'locked'] as Cell[]).map((c) => <span key={c} className="flex items-center gap-1.5"><span className={clsx('flex size-4 items-center justify-center rounded-full', CELL[c].cls)} />{CELL[c].label}</span>)}</div>
      </Card>
      <SidePanel label="Quyền của công cụ" open={!!tool} onClose={() => onTool(null)} className="rounded-xl border border-line xl:w-80 xl:shrink-0 xl:self-start"><div className="p-5 max-xl:pt-0">{tool ? <ToolPanel key={tool} sandbox={sandbox} tool={tool} /> : <p className="text-center text-ink-3">Bấm tên một công cụ ở hàng đầu để xem và đổi quyền.</p>}</div></SidePanel>
    </div>
  )
}

export function SandboxDetail() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const q = useSandbox(id)
  const list = useSandboxes()
  if (q.isPending) return <Loading />
  if (q.isError) return <div className="p-4 sm:p-8"><ErrorBox onRetry={() => q.refetch()}>Không mở được việc này.</ErrorBox></div>
  const d = q.data
  const asked = (params.get('tab') as Tab | null) ?? 'overview'
  const shown: Tab = (asked === 'tools' && !d.facing.tools) || (asked === 'send' && !d.facing.customer) ? 'overview' : asked  // a tab this kind of sandbox does not have
  const tab = shown
  const tool = params.get('tool')
  const setTab = (t: Tab) => setParams({ tab: t })
  const mine = list.data?.items.find((x) => x.id === d.id)
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8 [&>*]:shrink-0">
      <p className="text-[13px] text-ink-2"><Link to="/settings?tab=ai" className="hover:underline">Cài đặt → AI</Link> / <b className="text-ink">{d.title}</b></p>
      <PageHeader title={d.title} subtitle={d.about} action={<Badge tone={d.status === 'active' ? 'ok' : 'bad'}>{d.status === 'active' ? 'Đang chạy' : 'Đang tạm dừng'}</Badge>} />
      <Tabs value={shown} onChange={setTab} tabs={[
        { id: 'overview', label: 'Tổng quan', count: d.skills.length },
        ...(d.facing.tools ? [{ id: 'tools' as Tab, label: 'Công cụ', count: d.tools.filter((t) => t.on).length }] : []),
        ...(d.facing.customer ? [{ id: 'send' as Tab, label: 'Chế độ gửi' }] : []),
        { id: 'data', label: d.facing.customer ? 'Kênh & dữ liệu' : 'Nguồn & nơi gửi', count: d.inputs.channels.length + d.inputs.sources.length + d.feeds.length + d.pushes.length },
        { id: 'budget', label: 'Ngân sách' }]} />
      {tab === 'overview' && <Overview d={d} />}
      {tab === 'tools' && <Matrix d={d} sandbox={d.id} tool={tool} onTool={(t) => setParams(t ? { tab: 'tools', tool: t } : { tab: 'tools' })} />}
      {tab === 'send' && <SendPanel d={d} />}
      {tab === 'data' && (
        <Card className="flex max-w-3xl flex-col gap-3 p-5">
          {d.facing.customer && <><Label>Kênh</Label>
            {d.inputs.channels.length ? d.inputs.channels.map((c, i) => <p key={i} className="text-[13px]">{c.kind === 'messenger' ? 'Messenger' : c.kind} · {c.sends ? 'được gửi từ hệ thống' : 'chỉ nhận, nhân viên tự gửi'}</p>) : <p className="text-[13px] text-ink-3">Chưa nối kênh nào.</p>}</>}
          {!d.facing.customer && <><Label>Nguồn bài làm và bản ghi</Label>
            {d.feeds.length ? d.feeds.map((f) => <p key={f.id} className="text-[13px]"><b>{f.label}</b> · {f.where} · {f.active ? 'đang theo dõi' : 'tạm dừng'} · {f.lessons.done} {f.unit} xong{f.lessons.waiting > 0 && `, ${f.lessons.waiting} đang chờ`}{f.lessons.failed > 0 && <span className="text-bad">, {f.lessons.failed} lỗi</span>}</p>) : <p className="text-[13px] text-ink-3">Chưa gắn nguồn nào. Nối lớp Classroom hoặc Drive ở <Link to="/settings" className="font-semibold underline">Cài đặt → Kết nối Google</Link>; thư mục bản ghi buổi học vẫn gắn bằng dòng lệnh <code>add-lesson-source</code>.</p>}
            <Label>Thông báo gửi tới</Label>
            {d.pushes.length ? d.pushes.map((p) => <p key={p.id} className="text-[13px]"><b>{p.label}</b> · {p.where} · {p.active ? 'đang dùng' : 'tắt'}</p>) : <p className="text-[13px] text-ink-3">Chưa có nơi gửi. Thêm bằng dòng lệnh <code>add-notify-target --kind mezon</code>.</p>}</>}
          <Label>Nguồn dữ liệu ngoài</Label>
          {d.inputs.sources.length ? d.inputs.sources.map((s) => <p key={s.id} className="text-[13px]">{s.name} · {s.status === 'active' ? 'đang dùng' : 'đã khoá'}</p>) : <p className="text-[13px] text-ink-3">Chưa gắn nguồn nào. <Link to="/tools" className="font-semibold text-accent">Quản lý nguồn</Link></p>}
          {d.facing.customer && <p className="text-xs text-ink-3">Catalog nội bộ: {d.inputs.catalog_items} mục. <Link to="/data" className="font-semibold text-accent hover:underline">Xem ở Dữ liệu</Link></p>}
          <div className="mt-1 flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-3">{d.facing.customer && <SettingsLink to="/settings?tab=channels">Quản lý kênh ở Cài đặt → Kênh nhắn tin</SettingsLink>}<SettingsLink to="/settings?tab=notify">Quản lý nơi nhận thông báo ở Cài đặt → Thông báo</SettingsLink></div></Card>)}
      {tab === 'budget' && (mine ? <Card className="flex max-w-3xl flex-col gap-4 p-5"><div className="flex flex-col gap-3 sm:flex-row sm:gap-6"><Meter label="Lượt chạy hôm nay" value={mine.usage.runs} total={mine.budget.runs_per_day} /><Meter label="Token hôm nay" value={mine.usage.tokens} total={mine.budget.tokens_per_day} tone="ai" /></div>
        <p className="text-xs text-ink-3">Tối đa {mine.budget.tokens_per_day ? compact(mine.budget.tokens_per_day) : '–'} token mỗi ngày. Ngày tính theo giờ của doanh nghiệp.</p></Card> : <Loading />)}
    </div>
  )
}
