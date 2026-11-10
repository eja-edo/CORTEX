import clsx from 'clsx'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { explain } from '../api/client'
import { useSession, useSkill, useSkillVerb, useSkills } from '../api/hooks'
import type { SkillItem, SkillStatus } from '../api/types'
import { Badge, Button, Card, Empty, ErrorBox, Label, Loading, Notice, PageHeader, SidePanel, Tabs, type Tone } from '../components/ui'
import { skillTitle } from '../components/skillName'
import { Role } from '../api/enums'

const STATUS: Record<SkillStatus, [string, Tone]> = { live: ['Đang bật', 'ok'], shadow: ['Đang chạy thử', 'warn'], draft: ['Bản nháp', 'neutral'], retired: ['Đã tắt', 'neutral'] }
type Tab = 'all' | SkillStatus | 'deleted'

function Detail({ id, owner }: { id: string; owner: boolean }) {
  const q = useSkill(id)
  const verb = useSkillVerb()
  if (q.isPending) return <Loading />
  if (q.isError) return <ErrorBox onRetry={() => q.refetch()} />
  const s = q.data
  const need = Math.max(0, s.min_trial_runs - s.runs)
  const go = (v: 'trial' | 'live' | 'off' | 'again' | 'restore') => verb.mutate({ id, verb: v })
  const pct = Math.min(100, Math.round((s.runs / s.min_trial_runs) * 100))
  return (
    <div className="flex flex-col gap-4">
      <div><h2 className="text-base font-bold">{skillTitle(s.name)}</h2><div className="mt-1.5 flex gap-1.5"><Badge tone={STATUS[s.status][1]}>{STATUS[s.status][0]}</Badge>
        {s.source === 'card' && <Badge tone="ai">Từ thẻ chiến lược</Badge>}</div></div>
      <Link to={`/skills/${s.id}`} className="text-[13px] font-semibold text-accent">Xem chi tiết{s.can.edit ? ' và sửa' : ''}</Link>
      <p className="text-[13px] text-ink-2">{s.trigger}</p>
      {s.status === 'shadow' && (
        <div className="flex flex-col gap-2">
          <div className="flex justify-between text-[13px]"><span className="text-ink-2">Lượt chạy thử</span><b>{s.runs} / {s.min_trial_runs}</b></div>
          <div role="progressbar" aria-label="Tiến độ chạy thử" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} className="h-2 rounded-full bg-app"><div className="h-2 rounded-full bg-warn" style={{ width: `${pct}%` }} /></div>
          <p className="text-xs text-ink-2">{need > 0 ? `Cần thêm ${need} lượt thử và bạn đọc nháp thử trước khi bật.` : 'Đủ lượt thử. Đọc nháp thử rồi bật khi bạn yên tâm.'}</p>
        </div>)}
      {s.trial_drafts.length > 0 && (
        <div className="flex flex-col gap-2"><Label>Nháp thử gần nhất</Label>
          {s.trial_drafts.map((d, i) => (
            <div key={i} className="flex flex-col gap-1.5 rounded-lg bg-app p-3">
              {d.asked && <p className="text-xs text-ink-2">Khách: “{d.asked}”</p>}<p className="text-[13px] leading-snug">{d.text}</p>
              {d.blocked && <Badge tone="bad">Bị bộ kiểm chặn</Badge>}
            </div>))}
        </div>)}
      <div className="flex flex-col gap-1.5"><Label>Kỹ năng này được dùng</Label>{s.tools.map((t) => <p key={t} className="text-[13px]">✓ {t}</p>)}
        <p className="text-xs text-ink-3">{s.sends ? 'Có thể tự gửi khi doanh nghiệp bật chế độ tự gửi.' : 'Chỉ soạn nháp cho nhân viên duyệt.'} Chuyển người: {s.must_handoff.join(', ') || '–'}. {s.never_say_count} cụm cấm.</p></div>
      {verb.isError && <Notice tone="bad">{explain(verb.error)}</Notice>}
      {owner ? (
        <div className="flex flex-col gap-2">
          {s.status === 'shadow' && <Button variant="primary" disabled={!s.can.live} busy={verb.isPending} onClick={() => go('live')}>{s.can.live ? 'Bật' : `Bật (cần đủ ${s.min_trial_runs} lượt)`}</Button>}
          {s.can.trial && <Button variant="primary" busy={verb.isPending} onClick={() => go('trial')}>Chạy thử</Button>}
          {s.can.again && <Button busy={verb.isPending} onClick={() => go('again')}>Bật lại</Button>}
          {s.can.off && <Button busy={verb.isPending} onClick={() => go('off')}>Tắt kỹ năng</Button>}
          {s.can.restore && <Button variant="primary" busy={verb.isPending} onClick={() => go('restore')}>Khôi phục</Button>}
        </div>) : <Notice tone="neutral">Chỉ chủ mới đổi được trạng thái kỹ năng.</Notice>}
    </div>
  )
}

function Row({ s, active, onPick }: { s: SkillItem; active: boolean; onPick: () => void }) {
  const [label, tone] = s.deleted ? (['Đã xoá', 'bad'] as [string, Tone]) : STATUS[s.status]
  const text = s.status === 'shadow' ? `${label} ${s.runs}/10` : label
  return (
    <button role="row" aria-selected={active} onClick={onPick} className={clsx('flex w-full items-center gap-3 border-t border-line px-4 py-3.5 text-left', active ? 'bg-accent-soft' : 'hover:bg-app')}>
      <span className="min-w-0 flex-1"><b className="block truncate text-sm">{skillTitle(s.name)}</b><span className="block truncate text-xs text-ink-2">{s.description}</span></span>
      <span className="hidden w-44 shrink-0 text-[13px] text-ink-2 md:block xl:hidden min-[87.5rem]:block">{s.trigger}</span>
      <span className="shrink-0 md:w-36"><Badge tone={tone}>{text}</Badge></span>
      <span className="hidden w-20 shrink-0 text-[13px] font-medium sm:block">{s.runs.toLocaleString('vi-VN')}</span>
    </button>
  )
}

export function Skills() {
  const { data: me } = useSession()
  const q = useSkills()
  const [tab, setTab] = useState<Tab>('all')
  const [picked, setPicked] = useState<string>()
  const owner = me?.role === Role.OWNER
  const items = q.data?.items.filter((s) => (tab === 'deleted' ? s.deleted : !s.deleted && (tab === 'all' || s.status === tab))) ?? []
  const c = q.data?.counts
  return (
    <div className="flex h-full flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8 xl:overflow-hidden [&>*]:shrink-0">
      <PageHeader title="Kỹ năng" subtitle="Mỗi kỹ năng là một cách AI xử lý một tình huống. Kỹ năng mới phải chạy thử trước khi bật."
        action={<Link to="/skills/new"><Button variant="primary"><Plus className="size-4" aria-hidden />Tạo kỹ năng</Button></Link>} />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'all', label: 'Tất cả', count: c?.all }, { id: 'live', label: 'Đang bật', count: c?.live }, { id: 'shadow', label: 'Đang chạy thử', count: c?.shadow }, { id: 'draft', label: 'Bản nháp', count: c?.draft }, { id: 'retired', label: 'Đã tắt', count: c?.retired }, { id: 'deleted', label: 'Đã xoá', count: c?.deleted }]} />
      <div className="flex min-h-0 gap-5 xl:flex-1">
        <Card className="min-w-0 flex-1 xl:overflow-y-auto">
          <div role="row" className="hidden gap-3 rounded-t-xl bg-app px-4 py-3 text-[11px] font-semibold tracking-wider text-ink-3 uppercase md:flex">
            <span className="min-w-0 flex-1">Kỹ năng</span><span className="hidden w-44 shrink-0 md:block xl:hidden min-[87.5rem]:block">Kích hoạt</span><span className="w-36 shrink-0">Trạng thái</span><span className="w-20 shrink-0">Lượt chạy</span></div>
          {q.isPending ? <Loading /> : q.isError ? <ErrorBox onRetry={() => q.refetch()} /> : items.length === 0 ? <Empty>Không có kỹ năng nào ở mục này.</Empty>
            : items.map((s) => <Row key={s.id} s={s} active={s.id === picked} onPick={() => setPicked(s.id)} />)}
        </Card>
        <SidePanel label="Chi tiết kỹ năng" open={!!picked} onClose={() => setPicked(undefined)} className="rounded-xl border border-line xl:w-90 xl:shrink-0 xl:overflow-y-auto">
          <div className="p-5 max-xl:pt-0">{picked ? <Detail key={picked} id={picked} owner={!!owner} /> : <Empty>Chọn một kỹ năng để xem chi tiết.</Empty>}</div>
        </SidePanel>
      </div>
    </div>
  )
}
